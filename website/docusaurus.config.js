const webpack = require('webpack');

function rayforgeVersionPlugin() {
  return {
    name: 'rayforge-version-plugin',
    configureWebpack() {
      return {
        plugins: [
          new webpack.DefinePlugin({
            RAYFORGE_VERSION: JSON.stringify(process.env.RAYFORGE_VERSION || '0.0.0'),
            IS_PRERELEASE: JSON.stringify(process.env.IS_PRERELEASE || 'false'),
          }),
        ],
      };
    },
  };
}

module.exports = {
  title: 'SwiftCut',
  tagline: 'Free open-source laser cutter software — the LightBurn alternative for GRBL-based laser cutting and engraving',
  url: 'https://rayforge.org',
  baseUrl: '/',
  onBrokenLinks: 'warn',
  favicon: 'images/favicon.png',

  organizationName: 'barebaric',
  projectName: 'rayforge',

  customFields: {
    latestVersion: process.env.RAYFORGE_VERSION || '0.0.0',
    isPrerelease: process.env.IS_PRERELEASE === 'true',
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en', 'pt-BR', 'es', 'fr', 'de', 'zh-CN', 'uk'],
  },

  presets: [
    [
      '@docusaurus/preset-classic',
      {
        docs: {
          path: 'docs',
          routeBasePath: 'docs',
          sidebarPath: require.resolve('./sidebars.js'),
        },
        blog: {
          path: 'blog',
          routeBasePath: 'blog',
          blogTitle: 'SwiftCut Blog',
          blogDescription: 'News, release notes, tutorials, and tips about SwiftCut — free laser cutting and engraving software',
          postsPerPage: 10,
        },
        theme: {
          customCss: require.resolve('./src/css/custom.css'),
        },
        sitemap: {
          changefreq: 'weekly',
          priority: 0.5,
          ignorePatterns: ['/search'],
          filename: 'sitemap.xml',
        },
      },
    ],
  ],

  plugins: [
    rayforgeVersionPlugin,
    [
      require.resolve("@easyops-cn/docusaurus-search-local"),
      {
        hashed: true,
        language: ["en", "de", "es", "fr", "pt", "zh"],
        indexBlog: true,
        indexDocs: true,
        explicitSearchResultPath: true,
      },
    ],
    [
      '@docusaurus/theme-mermaid',
      {
        mermaid: {
          theme: 'base',
          themeVariables: {
            primaryColor: '#fff3e0',
            primaryTextColor: '#e65100',
            primaryBorderColor: '#ffb74d',
            lineColor: '#5f27cd',
            secondaryColor: '#e1f5fe',
            tertiaryColor: '#f3e5f5',
            background: '#ffffff',
            mainBkg: '#fff3e0',
            secondBkg: '#fff3e0',
            nodeBkg: '#fff3e0',
            nodeBorder: '#ffb74d',
            clusterBkg: '#fff3e0',
            clusterBorder: '#ffb74d',
            titleColor: '#e65100',
          },
        },
      },
    ],
  ],

  markdown: {
    mermaid: true,
    format: 'detect',
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },



  themeConfig: {
    metadata: [
      { name: 'keywords', content: 'laser cutter software, laser engraving software, LightBurn alternative, free laser software, open source laser software, GRBL, laser cutting software, laser control software, G-code sender, SwiftCut' },
      { name: 'author', content: 'SwiftCut Contributors' },
      { name: 'robots', content: 'index, follow' },
      { property: 'og:type', content: 'website' },
      { property: 'og:site_name', content: 'SwiftCut' },
      { name: 'twitter:title', content: 'SwiftCut - Free Open Source Laser Cutter Software' },
      { name: 'twitter:description', content: 'The complete creative studio for your laser cutter. Design, simulate, and control — with AI-powered tools, 3D preview, and a built-in sketcher.' },
    ],
    navbar: {
      title: 'SwiftCut',
      logo: {
        alt: 'SwiftCut Logo',
        src: 'images/icon.svg',
      },
      items: [
        {
          type: 'doc',
          docId: 'getting-started/installation',
          position: 'left',
          label: 'Documentation',
        },
        {
          to: '/resources/devices',
          label: 'Devices',
          position: 'left',
        },
        {
          type: 'docSidebar',
          sidebarId: 'developerSidebar',
          position: 'left',
          label: 'Developer',
        },
        {
          to: '/contributing',
          label: 'Contributing',
          position: 'left',
        },
        {
          to: '/sponsor',
          label: 'Sponsor',
          position: 'left',
        },
        {
          to: '/blog',
          label: 'Blog',
          position: 'left',
        },
        {
          type: 'localeDropdown',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      copyright: `Copyright © ${new Date().getFullYear()} SwiftCut Contributors`,
    },
  },
};
