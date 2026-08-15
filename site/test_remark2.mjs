import { remark } from "remark";
import html from "remark-html";
import fs from "fs";

async function main() {
  const raw = "- **2026-08-13**: Item 1\n\n- **2026-08-04**: Item 2\n\n- **2026-07-26**: Item 3\n\n- **2026-07-24**: Item 4\n";
  const result = await remark().use(html, { sanitize: false }).process(raw);
  console.log(result.toString());
}
main();
