/*
 * 前端演示数据（mock）
 * 这里的数据仅用于初步界面展示，不与任何后端接口通信。
 * 刷新页面后会恢复到初始状态。
 */
window.REVIEW_MOCK = {
  // 商品用于「评论」页的筛选下拉框
  products: [
    { id: 'P-001', name: '云感通勤双肩包 · 雾灰' },
    { id: 'P-002', name: '轻旅拉杆箱 20" · 石墨黑' },
    { id: 'P-003', name: '城市托特包 · 焦糖棕' },
    { id: 'P-004', name: '折叠旅行袋 · 沙岩色' }
  ],

  // 顶部统计卡片：接收量 / 成功分析 / 失败量
  stats: [
    {
      key: 'received',
      label: '接收量',
      value: '2,486',
      note: '近 7 天累计接收评论',
      trend: '↑ 12.4%',
      tone: 'primary',
      icon: 'inbox'
    },
    {
      key: 'analyzed',
      label: '成功分析',
      value: '2,391',
      note: '分析覆盖率 96.2%',
      trend: '↑ 8.1%',
      tone: 'success',
      icon: 'spark'
    },
    {
      key: 'failed',
      label: '失败量',
      value: '71',
      note: '其中 12 条等待重试',
      trend: '↓ 2.3%',
      tone: 'danger',
      icon: 'alert'
    }
  ],

  // 批次表格。状态与计数为 mock，用于展示导入与分析阶段。
  batches: [
    {
      id: 'B-20261024-004',
      file: 'reviews_20261024_bags.csv',
      accepted: 512,
      duplicates: 19,
      invalid: 3,
      status: '已完成',
      statusTone: 'success',
      time: '2026-10-24 14:32'
    },
    {
      id: 'B-20261024-003',
      file: 'reviews_20261024_morning.csv',
      accepted: 468,
      duplicates: 12,
      invalid: 0,
      status: '已完成',
      statusTone: 'success',
      time: '2026-10-24 10:05'
    },
    {
      id: 'B-20261023-002',
      file: 'reviews_20261023_full.csv',
      accepted: 1004,
      duplicates: 42,
      invalid: 7,
      status: '分析中',
      statusTone: 'processing',
      time: '2026-10-23 20:18'
    },
    {
      id: 'B-20261023-001',
      file: 'reviews_20261023_retry.csv',
      accepted: 371,
      duplicates: 8,
      invalid: 21,
      status: '部分失败',
      statusTone: 'warning',
      time: '2026-10-23 16:47'
    },
    {
      id: 'B-20261021-006',
      file: 'reviews_bad_columns.csv',
      accepted: 0,
      duplicates: 0,
      invalid: 17,
      status: '校验失败',
      statusTone: 'danger',
      time: '2026-10-21 11:26'
    }
  ],

  // 评论列表：analysisStatus 取 analyzed / queued / failed，
  // hasIssue 取 yes / no / unknown。
  comments: [
    {
      id: 'C-10042',
      productId: 'P-001',
      product: '云感通勤双肩包 · 雾灰',
      platform: '天猫',
      shop: '山野箱包旗舰店',
      rating: 2,
      date: '2026-10-24 09:12',
      analysisStatus: 'analyzed',
      hasIssue: 'yes',
      issueId: 'ISS-1042',
      issueCategory: '拉链卡顿',
      issueTone: 'rose',
      confidence: 0.93,
      content: '通勤用了两周，主仓拉链拉到一半就卡住，得来回蹭好几次才拉得上。面料和容量倒是不错，但这个拉链每天都要折腾。',
      evidence: ['拉到一半就卡住', '得来回蹭好几次']
    },
    {
      id: 'C-10041',
      productId: 'P-001',
      product: '云感通勤双肩包 · 雾灰',
      platform: '天猫',
      shop: '山野箱包旗舰店',
      rating: 3,
      date: '2026-10-24 08:40',
      analysisStatus: 'analyzed',
      hasIssue: 'yes',
      issueId: 'ISS-1051',
      issueCategory: '肩带设计',
      issueTone: 'amber',
      confidence: 0.89,
      content: '包本身很轻，装 14 寸电脑也放得下。只是肩带太滑，单肩背走两步就往下溜，下雨天更明显。',
      evidence: ['肩带太滑', '走两步就往下溜']
    },
    {
      id: 'C-10038',
      productId: 'P-003',
      product: '城市托特包 · 焦糖棕',
      platform: '京东',
      shop: 'NOMAD 箱包官方店',
      rating: 2,
      date: '2026-10-23 21:06',
      analysisStatus: 'analyzed',
      hasIssue: 'yes',
      issueId: 'ISS-1058',
      issueCategory: '容量不符',
      issueTone: 'blue',
      confidence: 0.86,
      content: '商品页写能放下 16 寸电脑，实际 14 寸机器塞进去就合不上拉链，容量和描述差挺多。通勤用有点尴尬。',
      evidence: ['14 寸机器塞进去就合不上', '容量和描述差挺多']
    },
    {
      id: 'C-10035',
      productId: 'P-002',
      product: '轻旅拉杆箱 20" · 石墨黑',
      platform: '天猫',
      shop: '远行箱包旗舰店',
      rating: 2,
      date: '2026-10-23 18:33',
      analysisStatus: 'analyzed',
      hasIssue: 'yes',
      issueId: 'ISS-1063',
      issueCategory: '拉杆晃动',
      issueTone: 'violet',
      confidence: 0.91,
      content: '箱子轮子很静音，但拉杆抽出来以后左右晃，走快一点感觉要散架。短途出差还能将就，长期用不太放心。',
      evidence: ['拉杆抽出来以后左右晃', '感觉要散架']
    },
    {
      id: 'C-10031',
      productId: 'P-001',
      product: '云感通勤双肩包 · 雾灰',
      platform: '天猫',
      shop: '山野箱包旗舰店',
      rating: 3,
      date: '2026-10-23 15:12',
      analysisStatus: 'analyzed',
      hasIssue: 'yes',
      issueId: 'ISS-1070',
      issueCategory: '色差',
      issueTone: 'teal',
      confidence: 0.72,
      content: '实物比页面图偏绿，雾灰看起来像灰绿色。背起来版型不错，肩带也舒服，但颜色确实有落差。',
      evidence: ['实物比页面图偏绿', '像灰绿色']
    },
    {
      id: 'C-10029',
      productId: 'P-003',
      product: '城市托特包 · 焦糖棕',
      platform: '京东',
      shop: 'NOMAD 箱包官方店',
      rating: 5,
      date: '2026-10-23 12:47',
      analysisStatus: 'analyzed',
      hasIssue: 'no',
      issueId: null,
      issueCategory: null,
      issueTone: null,
      confidence: 0.96,
      content: '包装完好，第二天就到。隔层设计合理，通勤装雨伞和水杯刚好，暂时没发现什么问题。',
      evidence: []
    },
    {
      id: 'C-10027',
      productId: 'P-004',
      product: '折叠旅行袋 · 沙岩色',
      platform: '天猫',
      shop: '远行箱包旗舰店',
      rating: 2,
      date: '2026-10-22 20:18',
      analysisStatus: 'analyzed',
      hasIssue: 'yes',
      issueId: 'ISS-1076',
      issueCategory: '异味',
      issueTone: 'olive',
      confidence: 0.84,
      content: '打开有一股很重的胶味，晾了三天还是明显，装衣服不太敢直接用。折叠起来倒是很省地方。',
      evidence: ['很重的胶味', '晾了三天还是明显']
    },
    {
      id: 'C-10025',
      productId: 'P-002',
      product: '轻旅拉杆箱 20" · 石墨黑',
      platform: '天猫',
      shop: '远行箱包旗舰店',
      rating: 3,
      date: '2026-10-22 16:54',
      analysisStatus: 'failed',
      hasIssue: 'unknown',
      issueId: null,
      issueCategory: null,
      issueTone: null,
      confidence: null,
      errorCode: 'ANALYSIS_TIMEOUT',
      content: '收到时箱体有一道划痕，客服已经处理。整体硬度还可以，就是希望包装再厚一点，别在运输中磕碰到。',
      evidence: []
    },
    {
      id: 'C-10022',
      productId: 'P-004',
      product: '折叠旅行袋 · 沙岩色',
      platform: '天猫',
      shop: '远行箱包旗舰店',
      rating: 3,
      date: '2026-10-22 11:03',
      analysisStatus: 'queued',
      hasIssue: 'unknown',
      issueId: null,
      issueCategory: null,
      issueTone: null,
      confidence: null,
      content: '走线在侧边开了一小段，装重物之后更明显。外观颜色挺好看，希望耐用一点。',
      evidence: []
    }
  ],

  // 问题组看板。状态固定为 proposed / confirmed / resolved / dismissed。
  issues: [
    {
      id: 'ISS-1042',
      status: 'proposed',
      title: '拉链中段卡顿',
      category: '拉链卡顿',
      categoryTone: 'rose',
      product: '云感通勤双肩包 · 雾灰',
      suggested: 6,
      confirmed: 0,
      severity: '高',
      updated: '今天 10:42',
      evidence: '“主仓拉链拉到一半就卡住，得来回蹭好几次才拉得上。”',
      description: '同一商品下多条评论提到主仓拉链在中段受阻，部分用户需要反复拉动才能闭合。',
      recommendation: '抽取同批次样衣复核拉链齿距与布带缝制，确认是否为批次性问题。',
      batches: 'B-20261024-004 / B-20261023-002'
    },
    {
      id: 'ISS-1070',
      status: 'proposed',
      title: '雾灰款存在明显色差',
      category: '色差',
      categoryTone: 'teal',
      product: '云感通勤双肩包 · 雾灰',
      suggested: 3,
      confirmed: 0,
      severity: '中',
      updated: '今天 09:18',
      evidence: '“实物比页面图偏绿，雾灰看起来像灰绿色。”',
      description: '评论反映实物比详情页图片偏绿，光线较暗时更明显，尚未排除屏幕色差因素。',
      recommendation: '核对近期拍摄样与实物，补充自然光场景图，并观察后续评论是否集中出现。',
      batches: 'B-20261024-003'
    },
    {
      id: 'ISS-1051',
      status: 'confirmed',
      title: '肩带过滑，单肩背易下滑',
      category: '肩带设计',
      categoryTone: 'amber',
      product: '云感通勤双肩包 · 雾灰',
      suggested: 9,
      confirmed: 5,
      severity: '中',
      updated: '今天 09:40',
      evidence: '“肩带太滑，单肩背走两步就往下溜。”',
      description: '已由运营人工确认，多个买家在通勤场景下反映肩带摩擦力不足，单肩背负时容易滑落。',
      recommendation: '与供应商确认肩带内衬材质，评估增加防滑纹或调整带宽。',
      batches: 'B-20261024-004 / B-20261023-001'
    },
    {
      id: 'ISS-1058',
      status: 'confirmed',
      title: '实际容量小于详情页描述',
      category: '容量不符',
      categoryTone: 'blue',
      product: '城市托特包 · 焦糖棕',
      suggested: 7,
      confirmed: 4,
      severity: '高',
      updated: '昨天 17:22',
      evidence: '“14 寸机器塞进去就合不上拉链，容量和描述差挺多。”',
      description: '评论集中指出商品页的电脑仓尺寸偏乐观，14 寸笔记本装入后主袋难以完全闭合。',
      recommendation: '实测内袋尺寸并更新详情页，避免继续使用“可放 16 寸电脑”的表述。',
      batches: 'B-20261023-002 / B-20261022-005'
    },
    {
      id: 'ISS-1029',
      status: 'resolved',
      title: '拉链头使用中断裂',
      category: '五金损坏',
      categoryTone: 'slate',
      product: '城市托特包 · 焦糖棕',
      suggested: 11,
      confirmed: 8,
      severity: '高',
      updated: '10 月 20 日',
      evidence: '“拉链头用了不到一个月就断在中间，包直接合不上。”',
      description: '已确认为个别批次的五金件强度不足，供应商完成补件，运营已逐一联系受影响买家。',
      recommendation: '跟进补件签收情况，并在下批次到货抽检拉链头抗拉强度。',
      batches: 'B-20261018-004',
      closeNote: '已补发拉链头并完成回访'
    },
    {
      id: 'ISS-1035',
      status: 'resolved',
      title: '折叠袋打开后有胶味',
      category: '异味',
      categoryTone: 'olive',
      product: '折叠旅行袋 · 沙岩色',
      suggested: 5,
      confirmed: 3,
      severity: '低',
      updated: '10 月 18 日',
      evidence: '“打开有一股很重的胶味，晾了三天还是明显。”',
      description: '已与供应商确认包装密封时间过长导致气味残留，后续批次改为到货后先行散味再入库。',
      recommendation: '继续观察新批次评价，必要时在详情页补充“首次使用建议通风”的说明。',
      batches: 'B-20261016-002',
      closeNote: '供应商已调整包装与散味流程'
    },
    {
      id: 'ISS-1033',
      status: 'dismissed',
      title: '物流时效偏慢',
      category: '物流时效',
      categoryTone: 'gray',
      product: '轻旅拉杆箱 20" · 石墨黑',
      suggested: 4,
      confirmed: 0,
      severity: '低',
      updated: '10 月 17 日',
      evidence: '“同一城市发了四天才到，中间物流一直没有更新。”',
      description: '问题指向承运商中转延迟，不属于商品本身；已记录并同步客服模板。',
      recommendation: '无需商品整改，继续按周观察物流差评占比。',
      batches: 'B-20261015-003',
      closeNote: '归类为物流承运问题'
    },
    {
      id: 'ISS-1040',
      status: 'dismissed',
      title: '拖动时轮子有异响',
      category: '轮子异响',
      categoryTone: 'slate',
      product: '轻旅拉杆箱 20" · 石墨黑',
      suggested: 2,
      confirmed: 0,
      severity: '低',
      updated: '10 月 15 日',
      evidence: '“在瓷砖地上拖动会有咯噔声，外面柏油路还好。”',
      description: '仅出现于特定地面材质，样本量不足以构成问题组，已由运营标记为暂不跟进。',
      recommendation: '保留为观察项；若同款评论增加再重新打开。',
      batches: 'B-20261013-004',
      closeNote: '样本量不足，标记暂不跟进'
    }
  ],

  // 人工复核队列：AI 生成的 suggested 关联，需人工接受 / 拒绝 / 改判。
  reviews: [
    {
      id: 'RV-201',
      issueId: 'ISS-1042',
      issueTitle: '拉链中段卡顿',
      category: '拉链卡顿',
      categoryTone: 'rose',
      commentId: 'C-10042',
      product: '云感通勤双肩包 · 雾灰',
      platform: '天猫',
      shop: '山野箱包旗舰店',
      confidence: 0.93,
      suggestedAt: '今天 10:42',
      comment: '通勤用了两周，主仓拉链拉到一半就卡住，得来回蹭好几次才拉得上。面料和容量倒是不错，但这个拉链每天都要折腾。',
      evidence: ['拉到一半就卡住', '得来回蹭好几次']
    },
    {
      id: 'RV-202',
      issueId: 'ISS-1058',
      issueTitle: '实际容量小于详情页描述',
      category: '容量不符',
      categoryTone: 'blue',
      commentId: 'C-10038',
      product: '城市托特包 · 焦糖棕',
      platform: '京东',
      shop: 'NOMAD 箱包官方店',
      confidence: 0.87,
      suggestedAt: '今天 10:36',
      comment: '商品页写能放下 16 寸电脑，实际 14 寸机器塞进去就合不上拉链，容量和描述差挺多。通勤用有点尴尬。',
      evidence: ['14 寸机器塞进去就合不上', '容量和描述差挺多']
    },
    {
      id: 'RV-203',
      issueId: 'ISS-1070',
      issueTitle: '雾灰款存在明显色差',
      category: '色差',
      categoryTone: 'teal',
      commentId: 'C-10031',
      product: '云感通勤双肩包 · 雾灰',
      platform: '天猫',
      shop: '山野箱包旗舰店',
      confidence: 0.64,
      suggestedAt: '今天 10:21',
      comment: '实物比页面图偏绿，雾灰看起来像灰绿色。背起来版型不错，肩带也舒服，但颜色确实有落差。',
      evidence: ['实物比页面图偏绿', '像灰绿色']
    },
    {
      id: 'RV-204',
      issueId: 'ISS-1051',
      issueTitle: '肩带过滑，单肩背易下滑',
      category: '肩带设计',
      categoryTone: 'amber',
      commentId: 'C-10041',
      product: '云感通勤双肩包 · 雾灰',
      platform: '天猫',
      shop: '山野箱包旗舰店',
      confidence: 0.81,
      suggestedAt: '今天 10:08',
      comment: '包本身很轻，装 14 寸电脑也放得下。只是肩带太滑，单肩背走两步就往下溜，下雨天更明显。',
      evidence: ['肩带太滑', '走两步就往下溜']
    }
  ],

  // 审计记录初始 mock，人工复核动作会在本地继续追加。
  auditLog: [
    {
      time: '今天 10:42',
      actor: 'AI Service',
      action: '生成关联建议',
      target: 'C-10042 → 拉链中段卡顿',
      tone: 'ai'
    },
    {
      time: '今天 10:38',
      actor: '林知远',
      action: '接受关联',
      target: 'C-10036 → 容量与描述不符',
      tone: 'human'
    },
    {
      time: '今天 10:21',
      actor: 'AI Service',
      action: '新建问题组',
      target: '雾灰款存在明显色差',
      tone: 'ai'
    },
    {
      time: '昨天 18:05',
      actor: '周可',
      action: '记录跟进',
      target: '肩带过滑 · 已联系供应商',
      tone: 'human'
    }
  ]
};
