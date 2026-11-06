export function validCommandSubnet(value) {
  if (value.length > 64 || !/^[0-9a-f:.]+\/(0|[1-9][0-9]{0,2})$/i.test(value)) return false
  const [address, bits] = value.split('/')
  if (address.includes(':')) {
    if (Number(bits) > 128) return false
    try { return new URL(`http://[${address}]/`).hostname.startsWith('[') } catch { return false }
  }
  return Number(bits) <= 32 && address.split('.').length === 4 && address.split('.').every(part => /^(0|[1-9][0-9]{0,2})$/.test(part) && Number(part) <= 255)
}
