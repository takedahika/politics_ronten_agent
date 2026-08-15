import { remark } from "remark";
import html from "remark-html";
import fs from "fs";

async function main() {
  const raw = fs.readFileSync("../topics/flag-desecration-law/timeline.md", "utf-8");
  const noHeader = raw.replace(/^\s*#+\s+.*(\r?\n|$)/m, "");
  const result = await remark().use(html, { sanitize: false }).process(noHeader);
  console.log(result.toString());
}
main();
