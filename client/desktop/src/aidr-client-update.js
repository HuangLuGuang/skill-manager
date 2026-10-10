(() => {
  const entry = document.getElementById('aidr-open-client-update')
  const settings = document.getElementById('settings-trigger')
  const check = document.getElementById('settings-check-update')
  if (!entry || !settings || !check) return
  entry.addEventListener('click', () => {
    settings.click()
    check.scrollIntoView({ block: 'center', behavior: 'smooth' })
    check.focus()
  })
})()
