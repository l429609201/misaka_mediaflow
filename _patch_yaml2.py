import os, re

path = 'web/src/pages/classify/index.jsx'
text = open(path, encoding='utf-8').read()

# 1. 删掉第96-215行的旧解析器（ini-like 格式），保留从第217行开始的分类弹窗
OLD_BLOCK_START = '// =============================================================================\n// 自定义代码格式解析器\n// 格式示例:'
OLD_BLOCK_END   = '\n// =============================================================================\n// 分类编辑弹窗'

s = text.index(OLD_BLOCK_START)
e = text.index(OLD_BLOCK_END)
text = text[:s] + text[e:]

# 2. 替换三处函数调用名
text = text.replace('cfgToText(ui)',      'uiCatsToYaml(ui)')
text = text.replace('cfgToText(uiCats)', 'uiCatsToYaml(uiCats)')
text = text.replace('parseCfgText(codeText)', 'parseYamlCfg(codeText)')

# 3. 更新 CodePanel 里的格式说明 pre 块
OLD_PRE = """`[分类名称]
target_dir = 目标子目录
media_type = all | movie | tv
genre_ids  = 16, 28, 35
country    = JP, CN
language   = ja, zh
keyword    = 动漫, 动画
keyword_dir= 番剧, 动漫
regex      = (?i)(OVA|OAD)
match_all  = false`"""

NEW_PRE = """`movie:
  动漫电影:
    genre_ids: '16'
    production_countries: 'JP'
  电影:

tv:
  动漫:
    genre_ids: '16'
    origin_country: 'JP'
    original_language: 'ja'
    keyword: '动漫,动画,番剧'
    regex: '(?i)(OVA|OAD)'
  电视剧:
  # 无字段 = 兜底分类`"""
text = text.replace(OLD_PRE, NEW_PRE)

# 4. 更新 CodePanel 字段说明列表
OLD_FIELDS = """        <div><Text code>genre_ids</Text> TMDB 类型 ID</div>
        <div><Text code>country</Text> 产地代码（JP/CN/US…）</div>
        <div><Text code>language</Text> 语言（ja/zh/en…）</div>
        <div><Text code>keyword</Text> 文件名关键词（逗号分隔）</div>
        <div><Text code>keyword_dir</Text> 目录名关键词</div>
        <div><Text code>regex</Text> 正则（文件名）</div>
        <Divider style={{ margin:'8px 0' }} />
        <div style={{ color:'#888' }}>无任何条件字段 = 兜底分类</div>
        <div style={{ color:'#888' }}># 开头行为注释</div>"""

NEW_FIELDS = """        <div><Text code>genre_ids</Text> TMDB 类型 ID（字符串）</div>
        <div><Text code>origin_country</Text> 产地（剧集），如 <Text code>'JP,CN'</Text></div>
        <div><Text code>production_countries</Text> 产地（电影）</div>
        <div><Text code>original_language</Text> 语言，如 <Text code>'ja,zh'</Text></div>
        <div><Text code>keyword</Text> 文件名关键词（逗号分隔）</div>
        <div><Text code>keyword_dir</Text> 目录名关键词</div>
        <div><Text code>regex</Text> 正则（匹配文件名）</div>
        <Divider style={{ margin:'8px 0' }} />
        <div style={{ color:'#888' }}>· 无任何字段 = 兜底分类</div>
        <div style={{ color:'#888' }}>· # 开头行为注释</div>
        <div style={{ color:'#888' }}>· movie/tv 下的分类继承适用对象</div>"""
text = text.replace(OLD_FIELDS, NEW_FIELDS)

# 5. 更新 CodePanel title Tag
text = text.replace(
    "<Tag color=\"blue\">自定义格式 · 非 JSON</Tag>",
    "<Tag color=\"blue\">YAML 格式 · 参考 MP</Tag>"
)

# 6. 更新 CodePanel 标题 "块格式" → "格式示例"
text = text.replace(
    "<div style={{ fontWeight:600, marginBottom:4 }}>块格式</div>",
    "<div style={{ fontWeight:600, marginBottom:4 }}>格式示例（YAML）</div>"
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

lines = len(text.splitlines())
print(f'Done: {lines} lines, {len(text)} bytes')

# 验证
checks = [
    ('parseYamlCfg 存在', 'parseYamlCfg' in text),
    ('uiCatsToYaml 存在', 'uiCatsToYaml' in text),
    ('旧 parseCfgText 已删', 'parseCfgText' not in text),
    ('旧 cfgToText 已删',    'cfgToText' not in text),
    ('YAML pre 示例',       "movie:" in text),
    ('YAML Tag',            'YAML 格式' in text),
    ('origin_country 字段说明', 'origin_country' in text),
]
for k, v in checks:
    print(('  [OK  ] ' if v else '  [MISS] ') + k)

os.remove(__file__)

