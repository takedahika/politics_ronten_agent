import { getTopicData, getTopicSlugs } from "@/lib/topics";
import { notFound } from "next/navigation";
import type { Metadata } from "next";

interface Props {
  params: Promise<{ slug: string }>;
}

export async function generateStaticParams() {
  const slugs = getTopicSlugs();
  return slugs.map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const topic = await getTopicData(slug);
  if (!topic) return { title: "Not Found" };
  return {
    title: `${topic.config.title} | 論点の現在地`,
    description: topic.config.description,
  };
}

const SECTIONS = [
  { id: "status", label: "Current Status", ja: "現在の状況", color: "#7dd3c8", key: "overview" },
  { id: "timeline", label: "Timeline", ja: "タイムライン", color: "#9b8fd4", key: "timeline" },
  { id: "facts", label: "Facts", ja: "確認された事実", color: "#6db3f2", key: "facts" },
  { id: "claims", label: "Claims", ja: "立場・主張", color: "#f2a96d", key: "claims" },
  { id: "issues", label: "Issues", ja: "主要な論点", color: "#f26d6d", key: "issues" },
  { id: "international", label: "International", ja: "国際比較", color: "#6df2a1", key: "international" },
  { id: "sources", label: "Sources", ja: "情報源", color: "#9a97a8", key: "sources" },
] as const;

type SectionKey = typeof SECTIONS[number]["key"];

export default async function TopicPage({ params }: Props) {
  const { slug } = await params;
  const topic = await getTopicData(slug);

  if (!topic) notFound();

  const content: Record<string, string> = {
    overview: topic.overview,
    timeline: topic.timeline,
    facts: topic.facts,
    claims: topic.claims,
    issues: topic.issues,
    international: topic.international,
    sources: topic.sources,
  };

  const newsletterArticles = topic.config.newsletter_articles ?? [];

  return (
    <article className="topic-page">
      <div className="container">

        {/* ヘッダー */}
        <header className="topic-header animate-in">
          <p className="topic-header-label">論点の現在地 / Topic</p>
          <h1 className="topic-title">{topic.config.title}</h1>
          <p className="topic-meta">
            {topic.lastUpdated ? `最終更新: ${topic.lastUpdated}` : "調査中"}
            {" · "}
            {(topic.config.keywords ?? []).join(" · ")}
          </p>
        </header>

        {/* ニュースレターCTA — コンパクトなハイパーリンクカード */}
        <div className="newsletter-cta animate-in">
          <div className="newsletter-cta-inner">
            <div className="newsletter-cta-header">
              <span className="newsletter-cta-eyebrow">✍️ ニュースレター連動エッセイ</span>
            </div>
            
            <p className="newsletter-cta-body">
              このトピックの背景と問いは、エッセイ「<strong>1年に3日だけ政治を考える</strong>」で取り上げられました。
            </p>

            {newsletterArticles.length > 0 && (
              <div className="newsletter-cta-articles">
                {newsletterArticles.map((article) => (
                  <a
                    key={article.url}
                    href={article.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="newsletter-article-card"
                  >
                    <span className="newsletter-article-icon">🔗</span>
                    <span className="newsletter-article-title">{article.title}</span>
                    <span className="newsletter-article-arrow">↗</span>
                  </a>
                ))}
              </div>
            )}

            <div className="newsletter-cta-footer">
              <a
                href="https://poli3year.substack.com"
                target="_blank"
                rel="noopener noreferrer"
                className="newsletter-cta-subscribe"
              >
                ニュースレターを無料購読する →
              </a>
            </div>
          </div>
        </div>

        {/* セクションナビ */}
        <nav className="topic-nav" aria-label="セクションナビゲーション">
          {SECTIONS.map((s) => (
            <a key={s.id} href={`#${s.id}`} className="topic-nav-item">
              {s.label}
            </a>
          ))}
        </nav>

        {/* 各セクション */}
        {SECTIONS.map((section) => (
          <section
            key={section.id}
            id={section.id}
            className="topic-section animate-in"
          >
            <div className="section-header">
              <span
                className="section-dot"
                style={{ background: section.color }}
              />
              <span className="section-label">{section.label}</span>
              <span className="section-title">{section.ja}</span>
            </div>
            <div
              className="md-content"
              dangerouslySetInnerHTML={{
                __html: content[section.key as SectionKey] || "<p style='color:var(--text-muted);font-size:0.85rem'>情報収集中...</p>",
              }}
            />
          </section>
        ))}

        {/* 変更履歴へのリンク */}
        <section className="topic-section" style={{ borderTop: "1px solid var(--border)", paddingTop: "2rem" }}>
          <div className="section-header">
            <span className="section-dot" style={{ background: "var(--gold)" }} />
            <span className="section-label">Change History</span>
            <span className="section-title">変更履歴</span>
          </div>
          <p style={{ fontSize: "0.875rem", color: "var(--text-muted)", lineHeight: "1.8" }}>
            このページの変更履歴はGitHubで確認できます。
            すべての更新はAIによる提案として作成され、人間が承認した後に公開されます。
          </p>
          <a
            href={`https://github.com/takedahika/politics_ronten_agent/commits/main/topics/${slug}`}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: "inline-block",
              marginTop: "1rem",
              fontSize: "0.8rem",
              color: "var(--gold)",
              textDecoration: "none",
              fontFamily: "var(--font-mono)",
              letterSpacing: "0.05em",
              borderBottom: "1px solid rgba(200,169,110,0.3)",
            }}
          >
            → GitHub で変更履歴を見る
          </a>
        </section>

      </div>
    </article>
  );
}
