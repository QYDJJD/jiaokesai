const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const source = fs.readFileSync(path.join(__dirname, '情景库演示-同资源时序优化.html'), 'utf8');
const context = { module: { exports: {} } };
vm.createContext(context);
vm.runInContext(source.match(/<script id="model">([\s\S]*?)<\/script>/)[1], context);
const m = context.module.exports;
const defaultInput = { period: 'night', pattern: 'back', people: 800, duration: 30, roundtrip: 30 };
let checked = 0;

function independentCheck(input, run) {
  assert.equal(run.passengers.length, input.people);
  assert.equal(new Set(run.passengers.map(p => p.id)).size, input.people);
  const computedWait = run.passengers.reduce((sum, p) => sum + p.depart - p.ready, 0);
  assert.ok(Math.abs(computedWait - run.totalWait) < 1e-6);
  assert.ok(Math.abs(run.meanWait - (input.people ? computedWait / input.people : 0)) < 1e-6);
  for (const mode of ['bus', 'taxi', 'metro']) {
    const passengers = run.passengers.filter(p => p.mode === mode);
    const byService = new Map();
    for (const p of passengers) {
      assert.ok(p.ready >= p.arrival);
      assert.ok(p.board >= p.ready && p.board < p.depart);
      const key = `${p.depart}:${p.vehicle}`;
      byService.set(key, (byService.get(key) || 0) + 1);
    }
    for (const [key, load] of byService) {
      const service = run.used.find(s => s.mode === mode && `${s.depart}:${s.vehicle}` === key);
      assert.ok(service, '每名旅客必须关联可用班次');
      assert.equal(load, service.load);
      assert.ok(load <= service.capacity);
    }
    const ordered = passengers.slice().sort((a, b) => a.ready - b.ready || a.id - b.id);
    for (let i = 1; i < ordered.length; i++) assert.ok(ordered[i].depart >= ordered[i - 1].depart, '先到先服务');
  }
  const busCalendar = run.calendar.filter(s => s.mode === 'bus').sort((a, b) => a.depart - b.depart);
  for (let i = 1; i < busCalendar.length; i++) assert.ok(busCalendar[i].open >= busCalendar[i - 1].depart, '公交上客窗口不重叠');
  if (run.plan) {
    const buses = run.calendar.filter(s => s.mode === 'bus' && s.extra);
    const taxis = run.calendar.filter(s => s.mode === 'taxi' && s.extra);
    assert.equal(buses.length, 9);
    assert.equal(new Set(buses.map(s => s.vehicle)).size, 3);
    assert.equal(buses.reduce((sum, s) => sum + s.capacity, 0), 360);
    assert.equal(taxis.length, 60);
    assert.equal(taxis.reduce((sum, s) => sum + s.capacity / 2, 0), 120);
    for (let b = 0; b < 3; b++) {
      const trips = buses.filter(s => s.vehicle === `备用公交${b + 1}`).sort((a, b) => a.depart - b.depart);
      assert.equal(trips.length, 3);
      assert.ok(trips[0].depart >= [13, 15, 17][b]);
      for (let i = 1; i < trips.length; i++) assert.equal(trips[i].depart - trips[i - 1].depart, input.roundtrip);
    }
    assert.ok(taxis[0].open >= 12);
  }
  for (const t of [0, 12, 25, input.duration, run.clear]) {
    const s = m.snapshot(run, t);
    assert.equal(s.future + s.walking + s.waiting + s.onboard + s.done, input.people, '过程人数守恒');
  }
  assert.equal(m.snapshot(run, run.clear).done, input.people);
  const eventTimes = run.passengers.flatMap(p => [p.ready, p.depart]);
  const independentlyMeasuredPeak = eventTimes.length ? Math.max(...eventTimes.map(t => run.passengers.filter(p => p.ready <= t && p.depart > t).length)) : 0;
  assert.equal(run.peak, independentlyMeasuredPeak);
  assert.equal(m.audit(input, run).length, 0);
}

const cases = [];
for (const period of ['night', 'day']) for (const pattern of ['front', 'uniform', 'back']) cases.push({ ...defaultInput, period, pattern });
cases.push({ ...defaultInput, roundtrip: 60 });
for (const people of [0, 200, 1200]) cases.push({ ...defaultInput, people });
for (const duration of [15, 60, 90]) cases.push({ ...defaultInput, duration });
cases.push({ ...defaultInput, people: 1200, duration: 90, roundtrip: 60 });
for (const input of cases) {
  const result = m.solve(input);
  for (const run of Object.values(result.runs)) independentCheck(input, run);
  assert.ok(result.runs.opt.totalWait <= result.runs.fixed.totalWait + 1e-6, '固定方案必须保留为候选');
  assert.equal(result.search.taxiCandidates, 60);
  assert.ok(result.search.busCandidates > 0);
  for (const mode of ['bus', 'taxi', 'metro']) {
    const regular = run => JSON.stringify(run.calendar.filter(s => s.mode === mode && !s.extra));
    assert.equal(regular(result.runs.fixed), regular(result.runs.opt), '常态能力不随方案改变');
    assert.equal(regular(result.runs.base), regular(result.runs.opt));
  }
  checked++;
}

const example = m.solve(defaultInput);
assert.ok(Math.abs(example.runs.fixed.meanWait - 23.5125) < 1e-6);
assert.ok(Math.abs(example.runs.opt.meanWait - 18.84625) < 1e-6);
assert.equal(example.runs.fixed.clear, 115);
assert.equal(example.runs.opt.clear, 86);
const unchanged = m.solve({ ...defaultInput, pattern: 'front' });
assert.ok(Math.abs(unchanged.runs.opt.meanWait - unchanged.runs.fixed.meanWait) < 1e-6, '保留无改善案例');
assert.throws(() => m.makePassengers({ ...defaultInput, people: -1 }));
assert.throws(() => m.makePassengers({ ...defaultInput, duration: 0 }));
assert.throws(() => m.makePassengers({ ...defaultInput, period: '__proto__' }));
assert.equal(m.busPlanFeasible(defaultInput, [13, 13, 17]), false);
assert.equal(m.busPlanFeasible(defaultInput, [13, 15, 25]), false, '不得与常态公交占用同一泊位');
assert.equal(m.busPlanFeasible(defaultInput, [12, 15, 17]), false, '不得提前使用尚未到位车辆');

// 与另一种累积容量核算对照，检查给定计划的实际发车分配。
const passengers = m.makePassengers(defaultInput);
for (const mode of ['bus', 'taxi', 'metro']) {
  const line = passengers.filter(p => p.mode === mode).sort((a, b) => a.ready - b.ready || a.id - b.id);
  const services = m.servicesFor(defaultInput, mode, example.search.plan);
  const production = m.dispatch(line, services, true);
  let index = 0;
  const expectedDepartures = [];
  for (const s of services) {
    let filled = 0;
    while (index < line.length && filled < s.capacity && line[index].ready < s.depart) {
      expectedDepartures.push(s.depart);
      index++;
      filled++;
    }
  }
  assert.equal(index, line.length);
  assert.deepEqual(Array.from(production.people, p => p.depart), expectedDepartures);
}
console.log(JSON.stringify({ passedScenarios: checked, checkedRuns: checked * 3, example: Object.fromEntries(Object.entries(example.runs).map(([key, r]) => [key, { meanWait: r.meanWait, peak: r.peak, clear: r.clear }])), optimalPlan: example.search.plan }, null, 2));
