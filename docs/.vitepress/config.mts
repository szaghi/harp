import { withMermaid } from 'vitepress-plugin-mermaid'

export default withMermaid({
  title: 'HARP',
  description: 'Horizon-Aware Recommender and Planner for deep-sky astrophotography',
  base: '/harp/',
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
