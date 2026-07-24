import { withMermaid } from 'vitepress-plugin-mermaid'

export default withMermaid({
  title: 'HARP',
  description: 'Horizon-Aware Recommender and Planner for deep-sky astrophotography',
  base: '/harp/',
  // Favicon. The href MUST carry the `base` prefix: files in docs/public are
  // served from the site root, which on GitHub Pages is /harp/, so a bare
  // '/harp-icon.svg' would work locally and 404 in production.
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/harp/harp-icon.svg' }],
  ],
  // mermaid 11 ships es2022 syntax; vitepress's default browser target
  // (chrome87/es2020) makes esbuild reject its chunks at build time
  vite: {
    build: { target: 'es2022' },
  },
  themeConfig: {
    // Nav-bar logo. Unlike the raw `head` href above, themeConfig.logo goes
    // through VitePress's own asset resolution, which prepends `base` itself —
    // adding '/harp/' here would double the prefix.
    logo: '/harp-icon.svg',
    nav: [
      { text: 'Home', link: '/' },
      {
        text: 'Guide',
        items: [
          { text: 'About',        link: '/guide/' },
          { text: 'Installation', link: '/guide/installation' },
          { text: 'Usage',        link: '/guide/usage' },
          { text: 'Android app',  link: '/guide/android' },
        ],
      },
      {
        text: 'Reference',
        items: [
          { text: 'Changelog', link: '/guide/changelog' },
        ],
      },
    ],
    sidebar: {
      '/guide/': [
        {
          text: 'Getting Started',
          items: [
            { text: 'About',        link: '/guide/' },
            { text: 'Installation', link: '/guide/installation' },
            { text: 'Usage',        link: '/guide/usage' },
            { text: 'Android app',  link: '/guide/android' },
          ],
        },
        {
          text: 'Reference',
          items: [
            { text: 'Changelog', link: '/guide/changelog' },
          ],
        },
      ],
    },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/szaghi/harp' },
    ],
  },
})
