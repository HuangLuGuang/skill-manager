// 与服务端一致支持 IP 地址和数字前缀 CIDR；保留原值用于定位错误。
const validIp = value => {
  const [address, prefix, extra] = value.trim().split('/')
  if (!address || extra !== undefined) return false
  const ipv6 = address.includes(':')
  if (ipv6) {
    if (!/^[0-9a-f:.]+$/iu.test(address)) return false
    try { new URL(`http://[${address}]/`) } catch { return false }
  } else {
    const octets = address.split('.')
    if (octets.length !== 4 || octets.some(part => !/^(0|[1-9]\d{0,2})$/u.test(part) || Number(part) > 255)) return false
  }
  return prefix === undefined || (/^\d+$/u.test(prefix) && Number(prefix) <= (ipv6 ? 128 : 32))
}

export const invalidIpEntries = values => values.flatMap((value, index) =>
  validIp(value) ? [] : [{ index: index + 1, value }]
)
