import assert from 'node:assert/strict'
import { 建聊天文档, 解析文档 } from '../lib/聊天文档.js'
// 生成有正确 xref 的最小测试 PDF，实际调用本机 Poppler，不依赖第三方生成库。
function pdf(pages) {
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
  const kids=[]
  for(const text of pages) {
    const id=objects.length+1, stream=text ? `BT /F1 12 Tf 72 720 Td (${text}) Tj ET` : ''
    kids.push(`${id} 0 R`)
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents ${id+1} 0 R >>`)
    objects.push(`<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`)
  }
  objects[1]=`<< /Type /Pages /Kids [${kids.join(' ')}] /Count ${pages.length} >>`
  let out='%PDF-1.4\n'; const offsets=[0]
  for(const [i,obj] of objects.entries()) { offsets.push(Buffer.byteLength(out)); out+=`${i+1} 0 obj\n${obj}\nendobj\n` }
  const xref=Buffer.byteLength(out)
  out+=`xref\n0 ${objects.length+1}\n0000000000 65535 f \n`+offsets.slice(1).map(n=>String(n).padStart(10,'0')+' 00000 n \n').join('')
  return Buffer.from(out+`trailer\n<< /Size ${objects.length+1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`)
}
const parsed=await 解析文档(pdf(['First page alpha','Second page beta']),'test.pdf')
assert.equal(parsed.total_pages,2)
assert.match(parsed.pages[0].text,/First page alpha/)
assert.match(parsed.pages[1].text,/Second page beta/)
assert.equal(parsed.limited,false)
await assert.rejects(()=>解析文档(pdf(['']),'scanned.pdf'),/没有可提取的文字/)
await assert.rejects(()=>解析文档(Buffer.from('not pdf'),'fake.pdf'),/不是有效 PDF/)
await assert.rejects(()=>解析文档(Buffer.from('text'),'fake.docx'),/目前支持/)
await assert.rejects(()=>解析文档(Buffer.from([0xc0,0xaf]),'bad.txt'),/编码/)
await assert.rejects(()=>解析文档(Buffer.from('x\0x'),'binary.txt'),/二进制/)
await assert.rejects(()=>解析文档(Buffer.alloc(10*1024*1024+1),'large.txt'),/10MB/)
const utf16=await 解析文档(Buffer.concat([Buffer.from([255,254]),Buffer.from('第一行\r\n第二行','utf16le')]),'utf16.txt')
assert.equal(utf16.pages[0].text,'第一行\n第二行')
assert.equal((await 解析文档(pdf(Array(101).fill('page')),'long.pdf')).limited,true)
assert.equal((await 解析文档(Buffer.from('文'.repeat(200001)),'long.txt')).limited,true)

const old={fetch,now:Date.now}; let now=1794000000000, downloads=0, calls=0, gate=null, oversized=false
Date.now=()=>now
const group={类型:'群',号码:'111'}, other={类型:'群',号码:'222'}, privateChat={类型:'私聊',号码:'333'}
const content='首行\n'+'字'.repeat(5996)+'🐟\n末行'
const msg=(id=1,ext='txt')=>({message_id:id,time:now/1000,user_id:123,message:[{type:'file',data:{file_id:'qq-file-'+id,name:'资料.'+ext}}]})
const call=async(action,args)=>{calls++;assert.equal(action,'get_group_file_url');assert.equal(args.group_id,'111');return{url:'https://qq-file.example/download'}}
globalThis.fetch=async(_url,options)=>{downloads++;assert.equal(options.headers,undefined,'不能转发 NapCat 令牌到文件下载站');if(gate)await gate;return new Response(content,{headers:oversized?{'content-length':String(11*1024*1024)}:{}})}
try {
  const docs=建聊天文档(); docs.收(group,[msg()]); docs.收(other,[msg(2)]); docs.收(privateChat,[msg(3)])
  assert.equal((await docs.读(group,{})).documents.length,1)
  assert.equal(downloads,0,'只登记和列出文件不能下载正文')
  assert.equal((await docs.读(other,{document_id:'doc-1-0'},call)).ok,false,'不能跨聊天读文件')
  assert.equal((await docs.读(group,{document_id:'doc-1-0',page:0},call)).ok,false)
  const [first,concurrent]=await Promise.all([docs.读(group,{document_id:'doc-1-0'},call),docs.读(group,{document_id:'doc-1-0'},call)])
  assert.equal(first.ok,true);assert.equal(concurrent.content,first.content);assert.equal(downloads,1);assert.equal(calls,1)
  assert.equal(first.line_start,1);assert.equal(first.next_page,1)
  const second=await docs.读(group,{document_id:'doc-1-0',page:first.next_page,start:first.next_start},call)
  assert.equal(first.content+second.content,content,'续读不能丢字或切断 emoji')
  assert.equal(second.next_page,null);assert.equal(second.line_end,3)
  docs.收(group,[msg()]); await docs.读(group,{document_id:'doc-1-0'},call)
  assert.equal(downloads,1,'重复轮询保留已解析缓存')
  docs.收(group,[msg(4)]);oversized=true
  assert.equal((await docs.读(group,{document_id:'doc-4-0'},call)).ok,false)
  oversized=false
  let release;gate=new Promise(r=>{release=r})
  const reading=docs.读(group,{document_id:'doc-4-0'},call)
  await new Promise(setImmediate);docs.保留聊天([]);release()
  assert.equal((await reading).ok,false,'停用时未完成的读取不能返回正文');gate=null
  docs.收(group,[msg(5)]); now+=3600000
  assert.equal((await docs.读(group,{})).documents.length,0)
  docs.收(group,Array.from({length:12},(_,i)=>msg(20+i)))
  assert.equal((await docs.读(group,{})).documents.length,10)
  docs.收(group,[{...msg(99),message_type:'private'}])
  assert.equal((await docs.读(group,{document_id:'doc-99-0'},call)).ok,false)
  const direct=msg(100);direct.message[0].data={name:'直链.txt',url:'https://qq-file.example/direct'}
  docs.收(group,[direct])
  const beforeCalls=calls
  assert.equal((await docs.读(group,{document_id:'doc-100-0'},call)).ok,true)
  assert.equal(calls,beforeCalls,'文件消息自带链接时不依赖取链接口')
  const local=msg(101);local.message[0].data={name:'本地.txt',url:'file:///etc/passwd'}
  docs.收(group,[local])
  const beforeDownloads=downloads
  assert.equal((await docs.读(group,{document_id:'doc-101-0'},call)).ok,false)
  assert.equal(downloads,beforeDownloads,'文件段不能要求读取本地路径')
  console.log('聊天文档：真实 PDF 页码/空页/页数上限、文本编码/长度、续读/emoji/行号、隔离/缓存/并发/大小/停用/过期通过')
} finally { globalThis.fetch=old.fetch;Date.now=old.now }
