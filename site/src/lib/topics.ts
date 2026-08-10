import fs from "fs";
import path from "path";
import matter from "gray-matter";
import { remark } from "remark";
import html from "remark-html";

const TOPICS_DIR = path.join(process.cwd(), "..", "topics");

export interface TopicConfig {
  id: string;
  title: string;
  slug: string;
  description: string;
  status: string;
  priority: string;
  keywords: string[];
  related_countries: string[];
  created_at: string;
}

export interface TopicData {
  config: TopicConfig;
  overview: string;
  timeline: string;
  facts: string;
  claims: string;
  issues: string;
  international: string;
  sources: string;
  lastUpdated: string | null;
}

async function markdownToHtml(content: string): Promise<string> {
  const result = await remark().use(html, { sanitize: false }).process(content);
  return result.toString();
}

function extractLastUpdated(content: string): string | null {
  const match = content.match(/\*最終更新: (.+?)\*/);
  return match ? match[1] : null;
}

export function getTopicSlugs(): string[] {
  if (!fs.existsSync(TOPICS_DIR)) return [];
  return fs
    .readdirSync(TOPICS_DIR)
    .filter((d) => fs.statSync(path.join(TOPICS_DIR, d)).isDirectory());
}

export async function getTopicData(slug: string): Promise<TopicData | null> {
  const topicDir = path.join(TOPICS_DIR, slug);
  const configPath = path.join(topicDir, "topic.yaml");

  if (!fs.existsSync(configPath)) return null;

  // YAML config を読み込む（gray-matter経由）
  const configRaw = fs.readFileSync(configPath, "utf-8");
  const { data: config } = matter(`---\n${configRaw}\n---`);

  const readSection = async (filename: string): Promise<string> => {
    const filepath = path.join(topicDir, filename);
    if (!fs.existsSync(filepath)) return "";
    const raw = fs.readFileSync(filepath, "utf-8");
    return await markdownToHtml(raw);
  };

  const overviewRaw = fs.existsSync(path.join(topicDir, "overview.md"))
    ? fs.readFileSync(path.join(topicDir, "overview.md"), "utf-8")
    : "";

  return {
    config: config as TopicConfig,
    overview: await readSection("overview.md"),
    timeline: await readSection("timeline.md"),
    facts: await readSection("facts.md"),
    claims: await readSection("claims.md"),
    issues: await readSection("issues.md"),
    international: await readSection("international.md"),
    sources: await readSection("sources.md"),
    lastUpdated: extractLastUpdated(overviewRaw),
  };
}

export async function getAllTopics(): Promise<TopicData[]> {
  const slugs = getTopicSlugs();
  const topics = await Promise.all(slugs.map(getTopicData));
  return topics.filter((t): t is TopicData => t !== null);
}
