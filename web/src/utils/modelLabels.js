export const modelLabel = (model) => {
  if (!model) return ''
  const upstream = model.upstream_name || model.name
  return [...new Set([model.display_name || upstream, model.provider_name, model.name].filter(Boolean))].join(' · ')
}
