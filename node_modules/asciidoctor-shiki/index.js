const shiki = require('shiki')
const deasync = require('deasync')

const AsciidoctorShiki = {
  initialize(_name, _backend, { document }) {
    const options = {}
    if (document.hasAttribute('shiki-theme')) {
      options.theme = document.getAttribute('shiki-theme')
    }
    this.highlighter = deasync((cb) => {
      shiki
        .getHighlighter(options)
        .then(highlighter => {
          cb(undefined, highlighter)
        })
    })()
    this.super()
  },
  highlight(_node, content, lang) {
    return this.highlighter.codeToHtml(content, { lang })
  },
  handlesHighlighting() {
    return true
  }
}

AsciidoctorShiki.default = AsciidoctorShiki
module.exports = AsciidoctorShiki
