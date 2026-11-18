// CVE-2026-112366: exercise the installed replacement, not just its package name.
// Upstream advisory: https://github.com/advisories/GHSA-fc5q-39xc-vjpf
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';

const root=path.resolve(process.argv[2]||'.');
const require=createRequire(path.join(root,'package.json'));
const lock=JSON.parse(fs.readFileSync(path.join(root,'package-lock.json'),'utf8'));
const expected=JSON.parse(fs.readFileSync(new URL('../glob-matcher/package.json',import.meta.url),'utf8'));
const copies=Object.entries(lock.packages).filter(([name])=>name.endsWith('node_modules/picomatch'));
assert(copies.length>0,'Expected installed glob matcher dependencies');
for(const [name,entry] of copies){
  assert.equal(entry.name,expected.name);
  assert.equal(entry.version,expected.version);
  assert.equal(entry.resolved,'file:../tools/glob-matcher');
  const installed=JSON.parse(fs.readFileSync(path.join(root,name,'package.json'),'utf8'));
  assert.equal(installed.name,expected.name);
  assert.equal(installed.version,expected.version);
  assert.deepEqual(installed.dependencies,expected.dependencies);
  const matcher=require(path.join(root,name));
  assert(matcher('**/*.{js,ts}')('src/example.ts'));
  assert(!matcher('**/*.js')('src/example.css'));
  assert(matcher('file.@(js|ts)')('file.js'));
  assert(!matcher('file.@(js|ts)')('file.css'));
  for(const pattern of ['+(*a)','+(*a)b','*(*)b','+(*?)b','+(*[ab])b','+(*|a)b']){
    const child=spawnSync(process.execPath,['-e',
      'const p=require(process.argv[1]);if(p(process.argv[2])(process.argv[3]))process.exit(2)',
      path.join(root,name),pattern,'a'.repeat(64)+'!'],{timeout:2000,encoding:'utf8'});
    assert.ifError(child.error);
    assert.equal(child.status,0,`Unsafe or incorrect repeated extglob: ${pattern}`);
  }
}
console.log(`Patched glob matching verified in ${copies.length} installed dependency location(s).`);
