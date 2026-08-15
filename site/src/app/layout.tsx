import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";

export const metadata: Metadata = {
  title: {
    template: "%s | 論点を365日追跡する",
    default: "論点を365日追跡する",
  },
  description:
    "人間が政治的な問いを起点に、関連する事実や議論を自動で収集・整理する。いま何が起きていて、どんな議論があるのか。このサイトは、議論の現在地を記録するメディアです。",
  openGraph: {
    siteName: "論点を365日追跡する",
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
                <span className="site-logo-ja">論点を365日追跡する</span>
              </Link>
              <nav className="site-nav">
                <Link href="/">論点一覧</Link>
                <a href="https://poli3year.substack.com" target="_blank" rel="noopener noreferrer">ニュースレター</a>
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
                論点を365日追跡する
              </div>
              <p className="footer-tagline">
                人間が政治的な問いを起点に、関連する事実や議論を自動で収集・整理する。<br />
                議論の現在地を記録するメディア。
              </p>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
