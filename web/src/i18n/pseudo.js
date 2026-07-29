const accentMap = {
  a: 'à', b: 'ƀ', c: 'ç', d: 'ð', e: 'ë', f: 'ƒ', g: 'ğ', h: 'ħ',
  i: 'ï', j: 'ĵ', k: 'ķ', l: 'ľ', m: 'ɱ', n: 'ñ', o: 'ö', p: 'þ',
  q: 'ʠ', r: 'ř', s: 'š', t: 'ţ', u: 'ü', v: 'ṽ', w: 'ŵ', x: 'ẋ',
  y: 'ÿ', z: 'ž',
}

export const pseudoLocalize = value => {
  const transformed = String(value).replace(/[A-Za-z]/g, character => {
    const lower = accentMap[character.toLowerCase()] || character
    return character === character.toUpperCase() ? lower.toUpperCase() : lower
  })
  return `[${transformed} ${'~'.repeat(Math.max(2, Math.ceil(transformed.length * 0.3)))}]`
}
