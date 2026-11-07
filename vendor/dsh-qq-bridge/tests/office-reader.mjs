import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { 建聊天文档, 解析文档 } from '../lib/聊天文档.js'
const W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
const S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const packageR = 'http://schemas.openxmlformats.org/package/2006/relationships'
// 完全生成的微型 Office 文档，不读取用户文件；ZIP 只用 Python 标准库构造。
const zip = files => execFileSync('python3', ['-I','-c', `import io,json,sys,zipfile
b=io.BytesIO()
with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
 for path,text in json.load(sys.stdin).items(): z.writestr(path,text)
sys.stdout.buffer.write(b.getvalue())`], { input: JSON.stringify(files), maxBuffer: 12*1024*1024 })
const packageFiles = main => ({
  '[Content_Types].xml': `<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/${main}" ContentType="application/vnd.openxmlformats-officedocument.${main.startsWith('word') ? 'wordprocessingml.document' : 'spreadsheetml.sheet'}.main+xml"/></Types>`,
  '_rels/.rels': `<Relationships xmlns="${packageR}"><Relationship Id="rId1" Type="${R}/officeDocument" Target="${main}"/></Relationships>`,
})
const docx = body => zip({ ...packageFiles('word/document.xml'), 'word/document.xml': `<w:document xmlns:w="${W}"><w:body>${body}</w:body></w:document>` })
const para = text => `<w:p><w:r><w:t>${text}</w:t></w:r></w:p>`
const doc = docx(para('开头🐟') + '<w:p><w:del><w:r><w:t>已删除内容</w:t></w:r></w:del><w:r><w:t>保留文字</w:t></w:r></w:p>' +
  `<w:tbl><w:tr><w:tc>${para('负责人')}</w:tc><w:tc>${para('小鱼')}</w:tc></w:tr></w:tbl>`)
const d = await 解析文档(doc, '中文.DOCX')
assert.equal(d.unit, 'section');assert.equal(d.total_pages, null)
assert.match(d.pages[0].text, /\[段落 1\] 开头🐟/)
assert.match(d.pages[0].text, /\[表格 1，第 1 行\] 负责人 \| 小鱼/)
assert.ok(!d.pages[0].text.includes('已删除内容'))
assert.equal(d.limited, false)

function xlsx({ sheets = ['任务表', '第二张'], firstCells, external = false } = {}) {
  const files = packageFiles('xl/workbook.xml')
  files['xl/workbook.xml'] = `<workbook xmlns="${S}" xmlns:r="${R}"><sheets>${sheets.map((name,i)=>`<sheet name="${name}" sheetId="${i+1}" r:id="table${i}"/>`).join('')}</sheets></workbook>`
  files['xl/_rels/workbook.xml.rels'] = `<Relationships xmlns="${packageR}">${sheets.map((_,i)=>`<Relationship Id="table${i}" Type="${R}/worksheet" Target="worksheets/custom${i}.xml"${external ? ' TargetMode="External"' : ''}/>`).join('')}<Relationship Id="strings" Type="${R}/sharedStrings" Target="sharedStrings.xml"/></Relationships>`
  files['xl/sharedStrings.xml'] = `<sst xmlns="${S}"><si><r><t>负责人</t></r><r><t>名字</t></r></si></sst>`
  sheets.forEach((_,i)=>{ files[`xl/worksheets/custom${i}.xml`] = `<worksheet xmlns="${S}"><sheetData><row r="1">${i===0 && firstCells !== undefined ? firstCells : '<c r="A1" t="s"><v>0</v></c><c r="C1" t="inlineStr"><is><t>小鱼🐟</t></is></c><c r="D1"><v>2.5</v></c><c r="E1" t="b"><v>1</v></c><c r="F1"><f>D1*2</f><v>5</v></c><c r="G1"><f>NOW()</f></c><c r="H1" t="e"><v>#DIV/0!</v></c>'}</row></sheetData></worksheet>` })
  return zip(files)
}
const x = await 解析文档(xlsx(), '清单.xlsx')
assert.equal(x.unit, 'sheet');assert.equal(x.pages.length,2);assert.equal(x.pages[0].title,'任务表');assert.equal(x.pages[1].title,'第二张')
for(const text of ['[A1] 负责人名字', '[C1] 小鱼🐟', '[D1] 2.5', '[E1] TRUE', '[F1] [公式缓存] 5', '[G1] [公式无缓存结果]', '[H1] [错误值] #DIV/0!']) assert.ok(x.pages[0].text.includes(text),text)
assert.ok(!x.pages[0].text.includes('[B1]'),'稀疏列不能压缩错位')
assert.match(x.notes.join(''),/日期.*序列数/)
const manySheets = await 解析文档(xlsx({ sheets: Array.from({length:21},(_,i)=>'表'+i) }), '多表.xlsx')
assert.equal(manySheets.pages.length,20);assert.equal(manySheets.limited,true)
assert.match(manySheets.pages[19].text,/H1/,'工作表数量上限不能让第一张表提前终止')
const cells = Array.from({length:20001},(_,i)=>`<c r="A${i+1}" t="inlineStr"><is><t>x</t></is></c>`).join('')
const manyCells = await 解析文档(xlsx({ sheets:['大表'], firstCells:cells }), '大表.xlsx')
assert.equal(manyCells.limited,true);assert.equal(manyCells.pages[0].locations.length,20000)
const longDoc = docx(para('🐟'.repeat(3500)) + para('末段'))
const oldFetch = fetch
try {
  globalThis.fetch=async()=>new Response(longDoc)
  const row={类型:'私聊',号码:'123'}, cache=建聊天文档()
  cache.收(row,[{message_id:1,time:Math.floor(Date.now()/1000),message:[{type:'file',data:{name:'长文.docx',url:'https://qq.invalid/file'}}]}])
  let args={document_id:'doc-1-0'}, content='', parts=[]
  do {
    const r=await cache.读(row,args);assert.equal(r.ok,true);assert.equal(r.page,null);assert.equal(r.line_start,null)
    assert.equal(r.section_title,'正文');assert.equal(r.section,1);assert.ok(r.source_refs.length)
    assert.ok(!/[\uD800-\uDBFF]$/.test(r.content),'续读不能切断 emoji')
    content+=r.content;parts.push(r)
    args={...args,page:r.next_page,start:r.next_start}
  } while(args.page)
  assert.equal(content,(await 解析文档(longDoc,'长文.docx')).pages[0].text)
  assert.deepEqual(parts[0].source_refs,['段落 1']);assert.deepEqual(parts[1].source_refs,['段落 1','段落 2'])
} finally { globalThis.fetch=oldFetch }
assert.equal((await 解析文档(docx(para('文'.repeat(200001))),'超长.docx')).limited,true)
await assert.rejects(()=>解析文档(docx(para('x'.repeat(17*1024*1024))),'膨胀.docx'),/上限/)
await assert.rejects(()=>解析文档(xlsx({external:true}),'外部.xlsx'),/结构/)
await assert.rejects(()=>解析文档(xlsx({firstCells:'<c r="A1" t="s"><v>999</v></c>'}),'损坏.xlsx'),/结构/)
await assert.rejects(()=>解析文档(Buffer.from('invalid'),'假.docx'),/目前支持/)
await assert.rejects(()=>解析文档(Buffer.from('old binary'),'旧.doc'),/目前支持/)
// 实体检查不能只看原始字节：UTF-16 的 '<!DOCTYPE' 字节序列不同，必须解码后再查。
for (const enc of ['utf-8', 'utf-16', 'utf-16-le', 'utf-16-be']) {
  const decl = enc === 'utf-8' ? 'utf-8' : 'utf-16'
  const entity = execFileSync('python3', ['-I','-c', `import io,sys,zipfile
s='<?xml version="1.0" encoding="${decl}"?><!DOCTYPE r [<!ENTITY a "A">]><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&a;</w:t></w:r></w:p></w:body></w:document>'
b=io.BytesIO()
with zipfile.ZipFile(b,'w') as z: z.writestr('word/document.xml', s.encode('${enc}'))
sys.stdout.buffer.write(b.getvalue())`])
  await assert.rejects(()=>解析文档(entity, `实体-${enc}.docx`), /结构/, `${enc} 的实体声明必须拒绝`)
}
console.log('Office：真实 ZIP/XML、正文/表格来源、Unicode 续读、工作表关系/稀疏单元格/公式缓存、容量上限和坏文件拒绝通过')
