import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {loadSiteData} from '../src/lib/data.ts';

test('editorial gallery survives restored collection snapshots without duplicating entries',()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'r9700-showcase-'));
  const previous=process.env.SITE_DATA_PATH;
  try {
    const snapshot=JSON.parse(fs.readFileSync('data/site-data.json','utf8'));
    snapshot.showcase=[{id:'external-existing',title:'Existing work'},{id:'cat-rescue-wan-20261024',title:'Old duplicate'}];
    const file=path.join(dir,'snapshot.json');
    fs.writeFileSync(file,JSON.stringify(snapshot));
    process.env.SITE_DATA_PATH=file;
    const data=loadSiteData();
    assert.equal(data.showcase.length,4);
    assert.equal(data.showcase.filter(item=>item.id==='cat-rescue-wan-20261024').length,1);
    assert.ok(data.showcase.some(item=>item.id==='external-existing'));
    for(const item of data.showcase.slice(0,3)) {
      assert.equal(item.gpuCount,2);
      assert.ok(fs.existsSync(path.join('public',item.url)));
      assert.ok(fs.existsSync(path.join('public',item.poster)));
    }
  } finally {
    if(previous===undefined)delete process.env.SITE_DATA_PATH;else process.env.SITE_DATA_PATH=previous;
    fs.rmSync(dir,{recursive:true,force:true});
  }
});
