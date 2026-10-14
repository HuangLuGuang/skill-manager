import { h } from 'vue'
import { SearchOutlined } from '@ant-design/icons-vue'
import { i18n } from '../i18n'
import AssetNameSearch from '../components/AssetNameSearch.vue'

export const withAssetNameSearch = column => ({
  ...column,
  filterDropdown: ({ selectedKeys, setSelectedKeys, confirm, clearFilters, visible }) => h(AssetNameSearch, { selectedKeys, setSelectedKeys, confirm, clearFilters, visible }),
  filterIcon: ({ filtered }) => h('button', {
    type: 'button',
    class: 'asset-name-search-trigger',
    'aria-label': i18n.global.t('localAssets.searchName'),
    title: i18n.global.t('localAssets.searchName'),
    style: { display: 'inline-flex', padding: '4px', border: 0, borderRadius: '4px', background: 'transparent', color: filtered ? '#245eea' : '#626b78', cursor: 'pointer' },
  }, [h(SearchOutlined)]),
  onFilter: (value, record) => String(record.name || '').toLocaleLowerCase().includes(String(value).trim().toLocaleLowerCase()),
})
