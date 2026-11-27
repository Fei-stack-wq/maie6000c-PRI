const {test} = require('node:test');
const assert = require('node:assert/strict');
require('../../frontend/api.js');
const api = globalThis.ReviewAPI;
test('filter values and identifiers are encoded; blank filters omitted', async () => {
  const calls=[];
  globalThis.fetch=async (path,options)=>{calls.push([path,options]);return {ok:true,json:async()=>[]};};
  await api.comments({product_id:'bag & blue',has_issue:'',limit:21,offset:20});
  const q=new URL(calls[0][0],'http://localhost');
  assert.equal(q.searchParams.get('product_id'),'bag & blue');
  assert.equal(q.searchParams.has('has_issue'),false);
  assert.equal(q.searchParams.get('offset'),'20');
  await api.comment('id/with space');
  assert.equal(calls[1][0],'/comments/id%2Fwith%20space');
});
test('upload preserves CSV text and idempotency key in POST JSON', async () => {
  const payload={platform:'amazon_sample',csv_text:'shop_id,product_id,body\ns,p,"text, quote"',idempotency_key:'retry-key'};
  globalThis.fetch=async(path,options)=>{
    assert.equal(path,'/review-batches');assert.equal(options.method,'POST');
    assert.deepEqual(JSON.parse(options.body),payload);
    return {ok:true,json:async()=>({batch_id:'saved'})};
  };
  assert.equal((await api.upload(payload)).batch_id,'saved');
});
test('rejected batch retains structured errors and batch ID for recovery UI', async () => {
  globalThis.fetch=async()=>({ok:false,status:422,json:async()=>({detail:{code:'batch_rejected',batch_id:'bad',errors:[{row_number:2,message:'missing body'}]}})});
  await assert.rejects(api.upload({}),e=>e.status===422 && e.detail.batch_id==='bad' && e.detail.errors.length===1);
});
test('non-JSON server error and network failure do not appear as success', async () => {
  globalThis.fetch=async()=>({ok:false,status:503,json:async()=>{throw new Error('html');}});
  await assert.rejects(api.stats(),/HTTP 503/);
  globalThis.fetch=async()=>{throw new TypeError('network down');};
  await assert.rejects(api.stats(),/network down/);
});
