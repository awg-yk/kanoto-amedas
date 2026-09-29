const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { parseAmedasCsv } = require('../src/parser');
const stations = require('../data/stations.json');

const p = parseAmedasCsv(fs.readFileSync(path.join(__dirname, '../data/2000-01-01.csv'), 'utf8'));
assert.strictEqual(p.stations.length, 85);
assert.strictEqual(p.times.length, 24);
assert.strictEqual(p.times[0], '2000-01-01T01:00');
assert.strictEqual(p.times[23], '2000-01-02T00:00');
assert.strictEqual(p.temp[0][0], 5.8);
assert.strictEqual(p.wind[0][0], 3.0);
assert.strictEqual(p.dir[0][0], 14); // 北西
for (const s of p.stations) assert.ok(stations[s], '座標なし: ' + s);
console.log('ok');
