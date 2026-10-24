const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const page = path.join(__dirname, '情景库演示-同资源时序优化.html');
const server = http.createServer((req, res) => {
  if (req.url === '/' || req.url === '/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
    fs.createReadStream(page).pipe(res);
    return;
  }
  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('Not found');
});
server.listen(8767, '127.0.0.1', () => console.log('Local: http://127.0.0.1:8767'));
process.on('SIGINT', () => server.close(() => process.exit(0)));
