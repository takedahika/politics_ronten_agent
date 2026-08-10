const isProd = process.env.NODE_ENV === 'production';

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
  // GitHub Pagesでサブフォルダにデプロイされるための設定
  basePath: isProd ? "/politics_ronten_agent" : "",
};

module.exports = nextConfig;
