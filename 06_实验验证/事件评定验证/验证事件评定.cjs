'use strict';
// Directly exercise the model embedded in the deliverable, with no browser dependency.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),html=fs.readFileSync(path.join(root,'07_成果输出/情景库思路演示.html'),'utf8');
const model=html.match(/<script id="assessment-model">([\s\S]*?)<\/script>/);
assert.ok(model,'交付页包含可独立验证的模型');
const context={module:{exports:{}}};vm.createContext(context);vm.runInContext(model[1],context);
const M=context.module.exports,plain=x=>JSON.parse(JSON.stringify(x));let checks=0,queueChecks=0;
function test(name,fn){fn();checks++;console.log('通过：'+name);}
function card(changes={}){const c=M.clone(M.examples()[1]);Object.assign(c.input,changes);return c;}
function near(a,b){assert.ok(Math.abs(a-b)<1e-7,`${a} != ${b}`);}

test('初始空白不生成等级，未知人数不当作0',()=>{const c=M.newCard(),r=M.assess(c);assert.equal(r.level,null);assert.equal(c.input.people,null);assert.equal(c.input.initial,null);assert.equal(r.runs.length,0);});
test('直接危险不受缺参或无效数字阻断',()=>{const c=M.newCard();c.input.danger='yes';c.input.duration=-2;const r=M.assess(c);assert.equal(r.level,1);assert.equal(r.runs.length,0);assert.ok(r.issues.length);});
test('当前已超限不受持续时间、能力或准备时间缺失阻断',()=>{for(const key of ['duration','capacity','prep','leadMin']){const c=card({initial:501,[key]:null}),r=M.assess(c);assert.equal(r.level,1);assert.equal(r.currentExcess,true);}});
test('恰好等于上限不被当成当前超限',()=>{const r=M.assess(card({initial:500}));assert.equal(r.currentExcess,false);assert.equal(r.level,2);});
test('已开始、来不及准备、恰好能准备三个边界',()=>{assert.equal(M.assess(card({leadMin:0,leadMax:0})).level,1);assert.equal(M.assess(card({leadMin:19,leadMax:19})).level,2);assert.equal(M.assess(card({leadMin:20,leadMax:20})).level,3);});
test('用户选择：5—30分钟按最早提示，并保留二级、三级',()=>{const r=M.assess(card({leadMax:30}));assert.equal(r.level,2);assert.deepEqual(plain(r.levels),[2,3]);assert.deepEqual(plain(r.margin),[-15,10]);});
test('开始窗口跨越已开始与准备边界时，不遗漏中间等级',()=>{assert.deepEqual(plain(M.assess(card({leadMin:0,leadMax:30})).levels),[1,2,3]);const c=card({nature:'no',people:100,initial:400,limit:500,duration:30,allowance:0,leadMin:0,leadMax:90,checkShapes:false});assert.deepEqual(plain(M.assess(c).levels),[1,2,3,4]);});
test('预测区间次序无效时不制造时间等级',()=>{const r=M.assess(card({leadMin:30,leadMax:5}));assert.equal(r.level,null);assert.ok(r.issues.some(i=>i.key==='leadMax'));});
test('短提前量不单独定义异常，正常且目标满足才为四级',()=>{const r=M.assess(card({nature:'no',leadMin:1,leadMax:1,capacity:1200}));assert.equal(r.level,4);assert.equal(M.assess(card({nature:'unknown',capacity:1200})).level,null);assert.equal(M.assess(card({nature:'no',danger:'unknown',capacity:1200})).level,null);});
test('无服务且有任务不生成有限完成时刻',()=>{const r=M.assess(card({capacity:0}));assert.equal(r.noCompletion,true);assert.equal(r.clear,null);assert.equal(r.remaining[0],200);});
test('明确零需求和零初始候客、零服务可以完成',()=>{const r=M.assess(card({people:0,initial:0,capacity:0,nature:'no'}));assert.equal(r.noCompletion,false);assert.equal(r.clear[0],0);assert.equal(r.level,4);});
test('缺少目标仍保留队列，缺少准备时间不捏造时间等级',()=>{const r=M.assess(card({limit:null,allowance:null,prep:null}));assert.ok(r.runs.length);near(r.peak[0],50);assert.equal(r.remaining,null);assert.equal(r.level,null);});
test('首次获知提前量不与当前剩余时间混用',()=>{const c=card();c.meta.firstInfoAt='2026-10-25T20:00';c.meta.firstExpectedAt='2026-10-25T21:00';const r=M.assess(c);assert.equal(r.firstLead,60);assert.equal(r.firstMargin,40);assert.equal(r.margin[0],-15);});
test('进入节奏与开始时间区间独立设置',()=>{const a=M.assess(card({leadMin:30,leadMax:30,shape:'uniform',checkShapes:false})),b=M.assess(card({leadMin:30,leadMax:30,shape:'front',checkShapes:false}));assert.equal(a.runs.length,1);assert.equal(b.runs.length,1);near(a.peak[0],50);near(b.peak[0],110);assert.equal(a.level,b.level);});
test('六组成对检查的等级与画像符合预期',()=>{const p=M.controls();assert.deepEqual(plain(p.map(x=>[x.a.level,x.b.level])),[[2,3],[3,3],[3,4],[3,4],[3,2],[1,2]]);near(p[1].a.peak[0],50);near(p[1].b.peak[0],110);near(p[3].b.peak[0],0);});
test('真实报道原型保留未知量，不将受影响人数、指令时间回填',()=>{const c=M.examples()[0];assert.equal(c.input.people,null);assert.equal(c.input.capacity,null);assert.equal(c.input.leadMin,null);assert.equal(c.meta.firstInfoAt,'');assert.equal(M.assess(c).level,null);assert.ok(c.facts.some(s=>s.includes('10008')));});
test('复制独立标识，修改数值转为假设，保留原卡',()=>{const original=M.examples()[0],copy=M.copyCard(original);M.numericInput(copy,'people',800);assert.notEqual(copy.id,original.id);assert.equal(copy.version,0);assert.equal(copy.parent.id,original.id);assert.equal(copy.evidence.people.kind,'研究假设');assert.equal(original.input.people,null);assert.equal(copy.facts.length,original.facts.length);});
test('保存生成新版本，记录改动，不覆盖原版本',()=>{const old=M.examples()[1],c=M.clone(old);M.numericInput(c,'people',300);const next=M.saveVersion(c,[old]);assert.equal(next.version,2);assert.equal(old.input.people,200);assert.deepEqual(plain(next.changed),[{field:'people',before:200,after:300}]);assert.equal(M.mergeLibrary([old],[next]).length,2);});
test('导入、导出往返不改变参数和证据，重复包可合并',()=>{const seeds=M.examples(),round=M.parseBundle(JSON.stringify(M.bundle(seeds)));assert.deepEqual(plain(round),plain(seeds));assert.equal(M.mergeLibrary(seeds,round).length,3);});
test('导入忽略外带旧等级，按当前输入复算',()=>{const b=M.bundle([card()]);b.cards[0].assessment.level=4;const imported=M.parseBundle(JSON.stringify(b))[0];assert.equal(M.assess(imported).level,2);assert.equal(Object.hasOwn(imported,'assessment'),false);});
test('同标识版本内容冲突、未知模板和无效数值被拒绝',()=>{const c=card();assert.throws(()=>M.mergeLibrary([c],[{...c,name:'篡改同版'}]),/冲突/);const b=M.bundle([c]);b.periods[c.periodRef].capacity=999;assert.throws(()=>M.parseBundle(JSON.stringify(b)),/定义不一致/);c.input.people=-1;assert.throws(()=>M.normalizeCard(c),/数值无效/);});

// Independent cumulative-arrival reflection: Q(t) = X(t) - min(0, min_{s<=t} X(s)).
// Evaluate all slope-change knots; extrema between knots are linear or reflected at zero.
function independent(x,lead,shape){
 const end=lead+x.duration,knots=[0,lead],D=x.duration,N=x.people,c=x.capacity/60;
 let pieces;if(shape==='uniform')pieces=[[D,N]];else if(shape==='front')pieces=[[D/3,.8*N],[2*D/3,.2*N]];else pieces=[[2*D/3,.2*N],[D/3,.8*N]];
 let elapsed=lead;for(const [duration] of pieces){elapsed+=duration;knots.push(elapsed);}
 function arrivals(t){let accumulated=0,start=lead;for(const [duration,count] of pieces){accumulated+=Math.max(0,Math.min(duration,t-start))*count/duration;start+=duration;}return accumulated;}
 let low=0,peak=0,last=0;for(const t of knots){const net=x.initial+arrivals(t)-c*t;low=Math.min(low,net);last=net-low;peak=Math.max(peak,last);}
 const remaining=Math.max(0,last-c*x.allowance);return {peak,remaining,end};
}
test('648组队列与独立累计流量反射计算一致',()=>{for(const lead of [0,30])for(const people of [0,200,800,1200])for(const duration of [15,30,120])for(const capacity of [0,300,1200])for(const initial of [0,100,600])for(const shape of ['uniform','front','back']){const x=card({leadMin:lead,leadMax:lead,people,duration,capacity,initial,shape}).input,a=M.queueRun(x,lead,shape),b=independent(x,lead,shape);near(a.peak,b.peak);near(a.remaining,b.remaining);assert.ok(a.trace.every(p=>p.q>=-1e-8));queueChecks++;}assert.equal(queueChecks,648);});
test('区间端点确实包住中间时点的客流指标',()=>{for(const shape of ['uniform','front','back'])for(const initial of [0,600]){const c=card({initial,leadMin:5,leadMax:30,shape,checkShapes:false}),r=M.assess(c);for(const lead of [10,20,25]){const mid=M.queueRun(c.input,lead,shape);assert.ok(mid.peak>=r.peak[0]-1e-8&&mid.peak<=r.peak[1]+1e-8);assert.ok(mid.remaining>=r.remaining[0]-1e-8&&mid.remaining<=r.remaining[1]+1e-8);}}});
test('交付页语法正确且不引入外部脚本',()=>{assert.equal((html.match(/<script[^>]*\bsrc=/g)||[]).length,0);for(const match of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(match[1]);assert.ok(html.includes('条件已修改，旧结果已隐藏'));});
console.log(JSON.stringify({model:M.version,checks,independentQueueCases:queueChecks,note:'规则与实现检查，不代表真实事件准确率或实际阈值标定'},null,2));
