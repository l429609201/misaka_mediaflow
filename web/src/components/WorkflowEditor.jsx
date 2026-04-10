// web/src/components/WorkflowEditor.jsx
// 可视化工作流编辑器 — 基于 @xyflow/react 拖拽连线
import { useState, useCallback, useRef, useMemo } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap,
  addEdge, useNodesState, useEdgesState,
  Handle, Position, MarkerType,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Card, Typography, Tag, theme, Input, Button, Space } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'

const { Text } = Typography

// ── 自定义节点 ──────────────────────────────────────────────────────
function WorkflowNode({ id, data, selected }) {
  const { token } = theme.useToken()
  const isStart = data.type === 'start'
  const isEnd = data.type === 'end'
  const color = data.color || '#1677ff'

  return (
    <div style={{
      background: token.colorBgContainer,
      border: `2px solid ${selected ? token.colorPrimary : color}`,
      borderRadius: 8, minWidth: 180, boxShadow: selected ? `0 0 0 2px ${token.colorPrimaryBg}` : '0 2px 8px rgba(0,0,0,0.08)',
    }}>
      {/* 顶部色条 */}
      <div style={{
        background: color, padding: '6px 12px', borderRadius: '6px 6px 0 0',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <Text style={{ color: '#fff', fontSize: 13, fontWeight: 600 }}>{data.label}</Text>
        <Tag style={{ margin: 0, fontSize: 10 }} color="rgba(255,255,255,0.2)">
          <span style={{ color: '#fff' }}>{data.type}</span>
        </Tag>
      </div>
      {/* 内容区 */}
      <div style={{ padding: '8px 12px', fontSize: 12, color: token.colorTextSecondary }}>
        {data.type === 'delay' && <Text type="secondary">延时 {data.params?.seconds || 5} 秒</Text>}
        {data.type === 'log' && <Text type="secondary">日志: {data.params?.message || '...'}</Text>}
        {data.type === 'notify' && <Text type="secondary">{data.params?.title || '通知'}</Text>}
        {data.type === 'condition' && <Text type="secondary">条件分支</Text>}
        {data.type === 'actor_cleanup' && <Text type="secondary">模式: {data.params?.mode || 'ghost'}</Text>}
        {!['delay','log','notify','condition','actor_cleanup'].includes(data.type) && (
          <Text type="secondary">{data.description || data.type}</Text>
        )}
      </div>
      {/* 连接点 */}
      {!isStart && <Handle type="target" position={Position.Top} style={{ background: color, width: 10, height: 10 }} />}
      {!isEnd && <Handle type="source" position={Position.Bottom} style={{ background: color, width: 10, height: 10 }} />}
    </div>
  )
}

const customNodeTypes = { workflowNode: WorkflowNode }

// ── 左侧面板 ────────────────────────────────────────────────────────
function NodePanel({ nodeTypes }) {
  const { token } = theme.useToken()

  const onDragStart = (e, nodeType) => {
    e.dataTransfer.setData('application/reactflow', JSON.stringify(nodeType))
    e.dataTransfer.effectAllowed = 'move'
  }

  // 按 category 分组
  const groups = useMemo(() => {
    const map = {}
    for (const nt of nodeTypes) {
      const cat = nt.category || 'other'
      if (!map[cat]) map[cat] = []
      map[cat].push(nt)
    }
    return map
  }, [nodeTypes])

  const catLabels = { flow: '流程控制', task: '任务节点', actor: '演员处理', other: '其他' }

  return (
    <div style={{
      width: 200, background: token.colorBgContainer, borderRight: `1px solid ${token.colorBorderSecondary}`,
      padding: 12, overflow: 'auto', height: '100%',
    }}>
      <Text strong style={{ fontSize: 14, marginBottom: 12, display: 'block' }}>动作组件</Text>
      {Object.entries(groups).map(([cat, items]) => (
        <div key={cat} style={{ marginBottom: 12 }}>
          <Text type="secondary" style={{ fontSize: 11, marginBottom: 4, display: 'block' }}>
            {catLabels[cat] || cat}
          </Text>
          {items.filter(n => !['start','end'].includes(n.type)).map(nt => (
            <div
              key={nt.type}
              draggable
              onDragStart={e => onDragStart(e, nt)}
              style={{
                padding: '6px 10px', marginBottom: 4, borderRadius: 6, cursor: 'grab',
                background: token.colorBgTextHover, border: `1px solid ${token.colorBorderSecondary}`,
                display: 'flex', alignItems: 'center', gap: 6, fontSize: 12,
              }}
            >
              <span style={{ color: nt.color, fontSize: 16 }}>●</span>
              {nt.label}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

// ── 编辑器主体 ────────────────────────────────────────────────────────
export default function WorkflowEditor({ initialNodes, initialEdges, nodeTypes: nodeTypeDefs, onChange }) {
  const reactFlowWrapper = useRef(null)
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes || [])
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges || [])
  const [reactFlowInstance, setReactFlowInstance] = useState(null)

  // 连线
  const onConnect = useCallback((params) => {
    setEdges(eds => addEdge({
      ...params,
      id: `e-${params.source}-${params.target}`,
      markerEnd: { type: MarkerType.ArrowClosed, color: '#999' },
      style: { stroke: '#999', strokeWidth: 2 },
      animated: false,
    }, eds))
  }, [setEdges])

  // 拖放新节点
  const onDragOver = useCallback((e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }, [])

  const onDrop = useCallback((e) => {
    e.preventDefault()
    const raw = e.dataTransfer.getData('application/reactflow')
    if (!raw) return
    const ntInfo = JSON.parse(raw)
    const position = reactFlowInstance.screenToFlowPosition({ x: e.clientX, y: e.clientY })
    const newId = `${ntInfo.type}-${Date.now()}`
    const newNode = {
      id: newId,
      type: 'workflowNode',
      position,
      data: { type: ntInfo.type, label: ntInfo.label, color: ntInfo.color, params: {}, description: '' },
    }
    setNodes(nds => nds.concat(newNode))
  }, [reactFlowInstance, setNodes])

  // 删除选中
  const onKeyDown = useCallback((e) => {
    if (e.key === 'Delete' || e.key === 'Backspace') {
      setNodes(nds => nds.filter(n => !n.selected || ['start','end'].includes(n.data?.type)))
      setEdges(eds => eds.filter(e => !e.selected))
    }
  }, [setNodes, setEdges])

  // 同步数据到外部
  const handleChange = useCallback(() => {
    if (onChange) onChange({ nodes, edges })
  }, [nodes, edges, onChange])

  // nodes/edges 变化时通知外部
  const onNodesChangeWrapped = useCallback((changes) => {
    onNodesChange(changes)
    setTimeout(() => { if (onChange) onChange({ nodes, edges }) }, 0)
  }, [onNodesChange, nodes, edges, onChange])

  const onEdgesChangeWrapped = useCallback((changes) => {
    onEdgesChange(changes)
    setTimeout(() => { if (onChange) onChange({ nodes, edges }) }, 0)
  }, [onEdgesChange, nodes, edges, onChange])

  // 转换 initialNodes 为 workflowNode 类型
  const processedNodes = useMemo(() => {
    return nodes.map(n => {
      if (n.type !== 'workflowNode') {
        const info = (nodeTypeDefs || []).find(nt => nt.type === n.data?.type) || {}
        return { ...n, type: 'workflowNode', data: { ...n.data, color: info.color || n.data?.color || '#1677ff' } }
      }
      return n
    })
  }, [nodes, nodeTypeDefs])

  return (
    <div style={{ display: 'flex', height: '100%' }} onKeyDown={onKeyDown} tabIndex={0}>
      <NodePanel nodeTypes={nodeTypeDefs || []} />
      <div ref={reactFlowWrapper} style={{ flex: 1, height: '100%' }}>
        <ReactFlow
          nodes={processedNodes}
          edges={edges}
          onNodesChange={onNodesChangeWrapped}
          onEdgesChange={onEdgesChangeWrapped}
          onConnect={onConnect}
          onInit={setReactFlowInstance}
          onDrop={onDrop}
          onDragOver={onDragOver}
          nodeTypes={customNodeTypes}
          defaultEdgeOptions={{
            markerEnd: { type: MarkerType.ArrowClosed, color: '#999' },
            style: { stroke: '#999', strokeWidth: 2 },
          }}
          fitView
          deleteKeyCode={['Delete', 'Backspace']}
          snapToGrid
          snapGrid={[15, 15]}
        >
          <Background gap={15} size={1} />
          <Controls />
          <MiniMap
            nodeColor={(n) => n.data?.color || '#1677ff'}
            style={{ height: 80 }}
          />
        </ReactFlow>
      </div>
    </div>
  )
}
