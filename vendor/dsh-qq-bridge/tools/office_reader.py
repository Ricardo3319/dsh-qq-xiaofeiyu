"""Read DOCX/XLSX text from stdin using only Python's standard library.

Open XML structure references:
https://learn.microsoft.com/en-us/office/open-xml/word/how-to-open-and-add-text-to-a-word-processing-document
https://learn.microsoft.com/en-us/office/open-xml/spreadsheet/how-to-retrieve-the-values-of-cells-in-a-spreadsheet
No archive extraction, external relationships, macros or formula evaluation.
"""
import io
import json
import posixpath
import sys
import zipfile
import xml.etree.ElementTree as ET

MAX_XML = 16 * 1024 * 1024
MAX_TEXT = 200000
MAX_BLOCKS = 20000


def local(tag):
    return tag.rsplit('}', 1)[-1]


def children(node, name):
    return [x for x in node if local(x.tag) == name]


def child(node, name):
    return next((x for x in node if local(x.tag) == name), None)


def word_text(node):
    kind = local(node.tag)
    if kind in ('del', 'drawing', 'pict'):
        return ''
    if kind == 't':
        return node.text or ''
    if kind in ('br', 'cr'):
        return '\n'
    if kind == 'tab':
        return '\t'
    return ''.join(word_text(x) for x in node)


class Reader:
    def __init__(self, archive):
        self.archive = archive
        self.xml_bytes = 0
        self.remaining = MAX_TEXT
        self.blocks = 0
        self.limited = False
        self.sections = []

    def xml(self, path):
        info = self.archive.getinfo(path)
        self.xml_bytes += info.file_size
        if self.xml_bytes > MAX_XML:
            raise ValueError('Office XML 解压后超过 16MB，请拆分文件')
        data = self.archive.read(info)
        # 不能只在原始字节上查：UTF-16/UTF-32 的 '<!DOCTYPE' 字节序列和 ASCII 不同，
        # 直接搜会漏掉，而 ElementTree 仍会展开内部实体。先按 BOM 解码再查。
        if data.startswith(b'\x00\x00\xfe\xff'):
            text = data[4:].decode('utf-32-be', 'replace')
        elif data.startswith(b'\xff\xfe\x00\x00'):
            text = data[4:].decode('utf-32-le', 'replace')
        elif data.startswith(b'\xef\xbb\xbf'):
            text = data[3:].decode('utf-8', 'replace')
        elif data.startswith(b'\xff\xfe'):
            text = data[2:].decode('utf-16-le', 'replace')
        elif data.startswith(b'\xfe\xff'):
            text = data[2:].decode('utf-16-be', 'replace')
        elif data.startswith(b'\x3c\x00'):  # 无 BOM 的 UTF-16LE：expat 仍会按 '<\0' 认出
            text = data.decode('utf-16-le', 'replace')
        elif data.startswith(b'\x00\x3c'):  # 无 BOM 的 UTF-16BE
            text = data.decode('utf-16-be', 'replace')
        else:
            text = data.decode('utf-8', 'replace')
        if '<!DOCTYPE' in text or '<!ENTITY' in text:
            raise ValueError('Office XML 含不支持的实体声明')
        return ET.fromstring(data)

    def add(self, section, label, text):
        if not text:
            return True
        if self.blocks >= MAX_BLOCKS or self.remaining <= 0:
            self.limited = True
            return False
        self.blocks += 1
        if len(text) > self.remaining:
            text = text[:self.remaining]
            self.limited = True
        section['blocks'].append({'label': label, 'text': text})
        self.remaining -= len(text)
        return not self.limited

    def word(self):
        body = child(self.xml('word/document.xml'), 'body')
        if body is None:
            raise ValueError('DOCX 缺少正文')
        section = {'title': '正文', 'blocks': []}
        self.sections.append(section)
        paragraph, table = 0, 0

        def blocks(node):
            for x in node:
                if local(x.tag) in ('p', 'tbl'):
                    yield x
                elif local(x.tag) in ('sdt', 'sdtContent', 'customXml', 'ins'):
                    yield from blocks(x)

        for node in blocks(body):
            if local(node.tag) == 'p':
                paragraph += 1
                if not self.add(section, f'段落 {paragraph}', word_text(node)):
                    break
            else:
                table += 1
                for row_no, row in enumerate(children(node, 'tr'), 1):
                    cells = [' / '.join(word_text(p) for p in children(c, 'p'))
                             for c in children(row, 'tc')]
                    if not self.add(section, f'表格 {table}，第 {row_no} 行', ' | '.join(cells)):
                        break
                if self.limited:
                    break
        return 'section', ['仅提取正文段落和表格行；不含页眉页脚、批注、脚注、文本框及图片。段落编号按正文顺序，不是 Word 页码；不还原合并单元格或嵌套表格布局。']

    def excel(self):
        workbook = self.xml('xl/workbook.xml')
        rels = self.xml('xl/_rels/workbook.xml.rels')
        paths = {}
        for rel in rels:
            if rel.get('TargetMode') == 'External':
                continue
            target = rel.get('Target', '')
            path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
            if path.startswith('xl/'):
                paths[rel.get('Id')] = (path, rel.get('Type', '').rsplit('/', 1)[-1])
        shared = []
        shared_path = next((p for p, kind in paths.values() if kind == 'sharedStrings'), None)
        if shared_path:
            for item in self.xml(shared_path):
                shared.append(''.join(x.text or '' for x in item.iter() if local(x.tag) == 't'))
        sheets = child(workbook, 'sheets')
        if sheets is None:
            raise ValueError('XLSX 缺少工作表列表')
        for sheet in list(sheets)[:20]:
            rid = next((v for k, v in sheet.attrib.items() if local(k) == 'id'), None)
            target = paths.get(rid)
            if not target or target[1] != 'worksheet':
                raise ValueError('XLSX 工作表关系缺失、外部引用或不是普通工作表')
            section = {'title': sheet.get('name', '未命名工作表'), 'blocks': []}
            self.sections.append(section)
            data = child(self.xml(target[0]), 'sheetData')
            if data is None:
                continue
            for row in data:
                for cell in children(row, 'c'):
                    address = cell.get('r')
                    if not address:
                        raise ValueError('XLSX 单元格缺少位置，无法准确标注来源')
                    value, formula = child(cell, 'v'), child(cell, 'f')
                    kind = cell.get('t', 'n')
                    text = value.text or '' if value is not None else ''
                    if kind == 's':
                        index = int(text)
                        if index < 0 or index >= len(shared):
                            raise ValueError('XLSX 共享文本索引无效')
                        text = shared[index]
                    elif kind == 'inlineStr':
                        inline = child(cell, 'is')
                        text = ''.join(x.text or '' for x in inline.iter() if local(x.tag) == 't') if inline is not None else ''
                    elif kind == 'b':
                        text = 'TRUE' if text == '1' else 'FALSE'
                    elif kind == 'e':
                        text = '[错误值] ' + text
                    if formula is not None:
                        text = '[公式缓存] ' + text if value is not None and value.text is not None else '[公式无缓存结果]'
                    if not self.add(section, address, text):
                        return 'sheet', self.excel_notes()
        self.limited = len(sheets) > 20
        return 'sheet', self.excel_notes()

    @staticmethod
    def excel_notes():
        return ['保留工作表名称和单元格位置；只读保存的值，不执行公式、宏或外部链接。公式缓存可能过期；无缓存会明确标注。数字使用原始值，日期/时间可能显示为序列数，不应用数字格式；不还原合并单元格、图表或图片。包含隐藏工作表和隐藏行列中的已存数据。']


def main():
    raw = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise ValueError('Office 文件必须非空且不超过 10MB')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        reader = Reader(archive)
        unit, notes = reader.word() if sys.argv[1] == '.docx' else reader.excel()
        return {'sections': reader.sections, 'unit': unit, 'notes': notes, 'limited': reader.limited}


if __name__ == '__main__':
    try:
        result = main()
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError, RuntimeError, NotImplementedError, RecursionError, MemoryError):
        result = {'error': '目前支持标准 DOCX/XLSX；文件结构损坏、加密、缺少内容或超过解析上限，请另存或拆分后发送'}
    print(json.dumps(result, ensure_ascii=False))
