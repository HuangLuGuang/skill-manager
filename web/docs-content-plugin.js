import { docsArticleOrder, docsContent } from './src/docs/content.js'

// Publish the same assembled source consumed by the online Help Center.
export function docsContentPlugin() {
  return {
    name: 'docs-content',
    generateBundle() {
      this.emitFile({
        type: 'asset', fileName: 'docs/content.json',
        source: JSON.stringify({ docsArticleOrder, docsContent }),
      })
    },
    configureServer(server) {
      server.middlewares.use('/docs/content.json', async (_request, response, next) => {
        try {
          const content = await server.ssrLoadModule('/src/docs/content.js')
          response.setHeader('Content-Type', 'application/json; charset=utf-8')
          response.setHeader('Cache-Control', 'no-store')
          response.end(JSON.stringify({ docsArticleOrder: content.docsArticleOrder, docsContent: content.docsContent }))
        } catch (error) {
          next(error)
        }
      })
    },
  }
}
