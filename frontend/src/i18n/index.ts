import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import { enUS } from './resources/en-US'
import { zhCN } from './resources/zh-CN'


void i18n.use(initReactI18next).init({
  resources: {
    'en-US': enUS,
    'zh-CN': zhCN,
  },
  lng: 'en-US',
  fallbackLng: 'en-US',
  supportedLngs: ['en-US', 'zh-CN'],
  interpolation: { escapeValue: false },
  returnNull: false,
})

export default i18n

