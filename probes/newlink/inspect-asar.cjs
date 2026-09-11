// Read-only inspection of installed application code, never login databases.
const fs = require('node:fs');
const archive = process.argv[2] || 'D:/IM/newLink/NewLink/resources/app.asar';
const terms = process.argv.slice(3);
if (!terms.length) throw Error('Provide search terms, e.g. atList mention sendTextMessage');
const fd = fs.openSync(archive, 'r');
try {
  const prefix = Buffer.alloc(16);
  fs.readSync(fd, prefix, 0, 16, 0);
  const length = prefix.readUInt32LE(12);
  if (length > 32 * 1024 * 1024) throw Error('Unexpected ASAR header size');
  const bytes = Buffer.alloc(length);
  fs.readSync(fd, bytes, 0, length, 16);
  const header = JSON.parse(bytes);
  const start = 8 + prefix.readUInt32LE(4);
  function walk(node, path = '') {
    for (const [name, file] of Object.entries(node.files || {})) {
      const current = path + name;
      if (file.files) walk(file, current + '/');
      else if (current.startsWith('plugin/im/dist/static/js/') && current.endsWith('.js') && !file.unpacked) {
        const data = Buffer.alloc(Number(file.size));
        fs.readSync(fd, data, 0, data.length, start + Number(file.offset));
        const source = data.toString('utf8');
        for (const term of terms) {
          let offset = -1;
          for (let match = 0; match < 3; match++) {
            offset = source.indexOf(term, offset + 1);
            if (offset < 0) break;
            console.log(JSON.stringify({ file:current, term, offset,
              excerpt:source.slice(Math.max(0, offset-160),offset+500) }));
          }
        }
      }
    }
  }
  walk(header);
} finally { fs.closeSync(fd); }
