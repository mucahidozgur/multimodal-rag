// react-pdf/pdfjs worker'ını public/ altına kopyalar.
// Worker dosyası modern .mjs sözdizimi kullandığı için webpack/Terser onu
// bundle edemiyor ("failed to parse input file"); public/ altından olduğu
// gibi servis edilir ve pdfjs.GlobalWorkerOptions.workerSrc ile işaret edilir.
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const src = path.join(root, "node_modules", "pdfjs-dist", "build", "pdf.worker.min.mjs");
const dest = path.join(root, "public", "pdf.worker.min.mjs");

if (!fs.existsSync(src)) {
  console.error("pdfjs worker bulunamadı:", src);
  process.exit(1);
}
fs.mkdirSync(path.dirname(dest), { recursive: true });
fs.copyFileSync(src, dest);
console.log("pdf.worker.min.mjs → public/ kopyalandı");
