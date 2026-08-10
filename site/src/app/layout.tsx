import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";

export const metadata: Metadata = {
  title: {
    template: "%s | 論点の現在地",
    default: "論点の現在地",
  },
  description:
    "人間が重要だと考えた社会的・政治的な問いをTopicとして継続的に調査し、現在の知識と議論の状態を記録するメディア。",
  openGraph: {
    siteName: "論点の現在地",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body>
        <header className="site-header">
          <div className="container-wide">
            <div className="site-header-inner">
              <Link href="/" className="site-logo">
                <span className="site-logo-en">Current State of Arguments</span>
                <span className="site-logo-ja">論点の現在地</span>
              </Link>
              <nav className="site-nav">
                <Link href="/">Topics</Link>
                <Link href="/newsletter">Newsletter</Link>
                <Link
                  href="https://github.com"
                  target="_blank"
                  rel="noopener"
                >
                  変更履歴 →
                </Link>
              </nav>
            </div>
          </div>
        </header>

        <main>{children}</main>

        <footer className="site-footer">
          <div className="container-wide">
            <div className="footer-inner">
              <div className="footer-brand">
                論点の現在地
                <span>Current State of Arguments</span>
              </div>
              <p className="footer-tagline">
                人間が重要だと考えた社会的・政治的な問いを継続的に調査し、
                現在の知識と議論の状態を記録する。
                より良い政治的・社会的な会話のための知的インフラ。
              </p>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
