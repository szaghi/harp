import { withMermaid } from 'vitepress-plugin-mermaid'

export default withMermaid({
  title: 'HARP',
  description: 'Horizon-Aware Recommender and Planner for deep-sky astrophotography',
  base: '/harp/',
  // mermaid 11 ships es2022 syntax; vitepress's default browser target
  // (chrome87/es2020) makes esbuild reject its chunks at build time
  vite: {
    build: { target: 'es2022' },
  },
  themeConfig: {
    nav: [
      { text: 'Home', link: '/' },
      {
        text: 'Guide',
        items: [
          { text: 'About',        link: '/guide/' },
          { text: 'Installation', link: '/guide/installation' },
          { text: 'Usage',        link: '/guide/usage' },
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
