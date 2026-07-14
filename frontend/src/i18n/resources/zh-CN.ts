export const zhCN = {
  translation: {
    common: {
      loading: '加载中',
      save: '保存',
      saving: '保存中...',
      back: '返回',
    },
    settings: {
      title: '设置',
      general: '通用设置',
      model: '模型连接',
      security: '账号安全',
      privacy: '隐私与数据',
    },
    settingsGeneral: {
      title: '通用设置', loading: '正在加载通用设置', language: '语言',
      languageDescription: '切换产品界面语言；Agent 回答仍跟随你的提问语言。',
      units: '计量单位', unitsDescription: '控制输入和展示方式，历史记录仍以公制标准值保存。',
      metric: '公制', imperial: '英制', timezone: '时区',
      timezoneDescription: '控制“今天”和每周边界，不改写历史记录日期。',
      description: '语言、计量单位和本地日期边界',
    },
  },
} as const
