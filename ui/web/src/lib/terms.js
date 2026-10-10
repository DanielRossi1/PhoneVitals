/**
 * Terms of use. Written once, in terms.md (copied to TERMS.md at the root of
 * the repository, which CI keeps identical); parsed here into blocks the
 * dialog renders without injecting HTML.
 */

import source from './terms.md?raw';

/** `**bold**` spans as [{text, bold}] segments. */
function inline(text) {
  return text.split(/(\*\*[^*]+\*\*)/).filter(Boolean)
    .map((part) => (part.startsWith('**') ? { text: part.slice(2, -2), bold: true } : { text: part }));
}

function parse(md) {
  const blocks = [];
  let list = null;
  for (const raw of md.split('\n')) {
    const line = raw.trim();
    if (line.startsWith('- ')) {
      if (!list) blocks.push(list = { type: 'list', items: [] });
      list.items.push(inline(line.slice(2)));
      continue;
    }
    list = null;
    if (!line || line.startsWith('# ') || /^\*\*Last updated/.test(line)) continue;
    if (line === '---') blocks.push({ type: 'rule' });
    else if (line.startsWith('## ')) blocks.push({ type: 'heading', text: line.slice(3) });
    else blocks.push({ type: 'paragraph', text: inline(line) });
  }
  return blocks;
}

export const TERMS = parse(source);
export const TERMS_UPDATED = /Last updated: ([\d-]+)/.exec(source)?.[1] ?? '';

/** The one line shown wherever the terms are referred to. */
export const TERMS_NOTICE = 'Provided as is, without warranty. Using PhoneVitals means accepting its terms of use.';
