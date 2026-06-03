const http = require("http");
const fs = require("fs");
const path = require("path");

const host = "127.0.0.1";
const port = Number(process.env.PORT || 8082);
const staticDir = path.join(__dirname, "static");

const types = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
};

http.createServer((req, res) => {
  const url = new URL(req.url, `http://${host}:${port}`);
  const requestPath = url.pathname === "/" ? "/index.html" : url.pathname;
  const filePath = path.normalize(path.join(staticDir, requestPath));

  if (!filePath.startsWith(staticDir)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404);
      res.end("Not found");
      return;
    }
    res.writeHead(200, {"Content-Type": types[path.extname(filePath)] || "application/octet-stream"});
    res.end(data);
  });
}).listen(port, host, () => {
  console.log(`GROUND STATION 2 running at http://${host}:${port}`);
  console.log("Open in Chrome/Edge and press CONNECT USB for Ground Station 1 serial.");
});
