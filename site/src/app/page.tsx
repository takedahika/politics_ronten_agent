import Link from "next/link";
import { getAllTopics } from "@/lib/topics";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "論点の現在地",
  description:
    "人間が重要だと考えた社会的・政治的な問いをTopicとして継続的に調査し、現在の知識と議論の状態を記録するメディア。",
};

const PRIORITY_LABEL: Record<string, string> = {
  high: "HIGH PRIORITY",
  normal: "TRACKING",
  low: "LOW PRIORITY",
};

export default async function HomePage() {
  const topics = await getAllTopics();

  return (
    <>
      {/* ヒーロー */}
      <section className="home-hero">
        <div className="container">
          <p className="home-hero-label">Current State of Arguments</p>
          <h1 className="home-hero-title">
            論点の
            <br />
            現在地
          </h1>
          <p className="home-hero-desc">
            人間が「これは重要だ」と思った社会的・政治的な問いを起点に、
            自動的に情報を収集・整理する。
            <br />
            <br />
            現在、何が分かっていて、何が議論されていて、
            何がまだ分かっていないのか。
          </p>
        </div>
      </section>

      {/* Topic 一覧 */}
      <section className="home-topics-section">
        <div className="container">
          <p className="home-section-label">追跡中のTopic — {topics.length}件</p>

          {topics.length === 0 ? (
            <p style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>
              Topicがまだ登録されていません。
            </p>
          ) : (
            <div>
              {topics.map((topic, i) => (
                <Link
                  key={topic.config.slug}
                  href={`/topics/${topic.config.slug}`}
                  className={`topic-card animate-in`}
                  style={{ animationDelay: `${i * 0.05}s` }}
                >
                  <p className="topic-card-priority">
                    {PRIORITY_LABEL[topic.config.priority] ?? "TRACKING"}
                  </p>
                  <h2 className="topic-card-title">{topic.config.title}</h2>
                  <p className="topic-card-desc">{topic.config.description}</p>
                  <div className="topic-card-meta">
                    {topic.lastUpdated && (
                      <span>最終更新: {topic.lastUpdated}</span>
                    )}
                    <div className="topic-card-keywords">
                      {(topic.config.keywords ?? []).slice(0, 3).map((kw) => (
                        <span key={kw} className="keyword-tag">
                          {kw}
                        </span>
                      ))}
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* メディアについて */}
      <section style={{ borderTop: "1px solid var(--border)", padding: "3rem 0" }}>
        <div className="container">
          <p
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: "0.65rem",
              letterSpacing: "0.2em",
              textTransform: "uppercase",
              color: "var(--text-muted)",
              marginBottom: "1.5rem",
            }}
          >
            About this project
          </p>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
              gap: "1.5rem",
            }}
          >
            {[
              {
                label: "Newsletter",
                desc: "人間が書く政治エッセイ。「これは重要だ」という問いから始まる。",
              },
              {
                label: "Topic",
                desc: "継続調査する知識の現在地。何が分かっていて、何が議論されているか。",
              },
              {
                label: "Automated tracking, human approved",
                desc: "自動で情報を収集し、人間が承認する。すべての更新はGitHubで追跡可能。",
              },
            ].map((item) => (
              <div
                key={item.label}
                style={{
                  padding: "1.25rem",
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                }}
              >
                <p
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: "0.7rem",
                    color: "var(--gold)",
                    letterSpacing: "0.1em",
                    marginBottom: "0.5rem",
                  }}
                >
                  {item.label}
                </p>
                <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", lineHeight: "1.7" }}>
                  {item.desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
