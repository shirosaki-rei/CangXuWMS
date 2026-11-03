/**
 * PDA 打样诊断（T-01-7 的核心风险点）。
 *
 * 任务清单里写的是「第一周必须做工业 PDA 扫码打样，若 Expo 条码识别不兼容现场 PDA，
 * 需退出 Expo 或加 config plugin，代价 5–10d」。
 *
 * 这个页面把结论做成可判读的清单：装到真机上逐项看，全绿就不用退 Expo。
 */
import { useEffect, useState } from 'react'
import { Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native'
import Constants from 'expo-constants'
import * as SQLite from 'expo-sqlite'
import * as SecureStore from 'expo-secure-store'
import { useCameraPermissions } from 'expo-camera'
import { request } from '../api/client'
import { useSession } from '../stores/session'

interface Check {
  name: string
  ok: boolean | null
  detail: string
}

export default function DiagnosticsScreen() {
  const { session } = useSession()
  const [perm, requestPerm] = useCameraPermissions()
  const [checks, setChecks] = useState<Check[]>([])
  const [running, setRunning] = useState(false)

  async function run() {
    setRunning(true)
    const out: Check[] = []

    // 1. 运行环境
    out.push({
      name: '运行环境',
      ok: true,
      detail: `${Platform.OS} ${String(Platform.Version)} · Expo ${Constants.expoConfig?.sdkVersion ?? '?'} · ${Constants.expoConfig?.name ?? ''}`,
    })

    // 2. SecureStore（token 持久化）
    try {
      await SecureStore.setItemAsync('__diag', 'ok')
      const v = await SecureStore.getItemAsync('__diag')
      await SecureStore.deleteItemAsync('__diag')
      out.push({ name: 'SecureStore', ok: v === 'ok', detail: v === 'ok' ? '可读写' : '读回不一致' })
    } catch (e) {
      out.push({ name: 'SecureStore', ok: false, detail: (e as Error).message })
    }

    // 3. SQLite（离线队列的底座）
    try {
      const db = await SQLite.openDatabaseAsync('diag.db')
      await db.execAsync('CREATE TABLE IF NOT EXISTS t(v TEXT); DELETE FROM t;')
      await db.runAsync('INSERT INTO t VALUES (?)', ['ok'])
      const row = await db.getFirstAsync<{ v: string }>('SELECT v FROM t LIMIT 1')
      out.push({ name: 'SQLite', ok: row?.v === 'ok', detail: row?.v === 'ok' ? '可读写（WAL 可用）' : '读回不一致' })
    } catch (e) {
      out.push({ name: 'SQLite', ok: false, detail: (e as Error).message })
    }

    // 4. 摄像头权限
    out.push({
      name: '摄像头权限',
      ok: !!perm?.granted,
      detail: perm?.granted ? '已授权' : '未授权（点下面按钮申请）',
    })

    // 5. 网络可达
    if (session) {
      try {
        const t0 = Date.now()
        await request({ base: session.apiBase, path: '/auth/captcha', timeoutMs: 5000 })
        out.push({ name: 'WMS 接口', ok: true, detail: `${session.apiBase} · ${Date.now() - t0} ms` })
      } catch (e) {
        out.push({ name: 'WMS 接口', ok: false, detail: (e as Error).message })
      }
    } else {
      out.push({ name: 'WMS 接口', ok: null, detail: '未登录，跳过' })
    }

    setChecks(out)
    setRunning(false)
  }

  useEffect(() => { void run() }, [perm?.granted])

  const allOk = checks.length > 0 && checks.every((c) => c.ok !== false)

  return (
    <ScrollView contentContainerStyle={s.wrap}>
      <Text style={s.title}>PDA 打样诊断</Text>
      <Text style={s.hint}>
        装到现场 PDA 上逐项确认。摄像头与键盘楔入这两种扫码方式都要在「扫码」页各试一次，
        能扫出码才说明不用退出 Expo。
      </Text>

      <Pressable style={s.btn} onPress={() => void run()}>
        <Text style={s.btnText}>{running ? '检测中…' : '重新检测'}</Text>
      </Pressable>
      {!perm?.granted && (
        <Pressable style={[s.btn, s.btnGhost]} onPress={requestPerm}>
          <Text style={[s.btnText, { color: '#0d5bb5' }]}>申请摄像头权限</Text>
        </Pressable>
      )}

      <Text style={[s.verdict, allOk ? s.okText : s.warnText]}>
        {checks.length === 0 ? '' : allOk ? '环境自检全部通过' : '有项目未通过，见下方红项'}
      </Text>

      {checks.map((c) => (
        <View key={c.name} style={s.row}>
          <Text style={[s.mark, c.ok === false ? s.fail : c.ok ? s.pass : s.skip]}>
            {c.ok === false ? '✗' : c.ok ? '✓' : '–'}
          </Text>
          <View style={{ flex: 1 }}>
            <Text style={s.name}>{c.name}</Text>
            <Text style={s.detail}>{c.detail}</Text>
          </View>
        </View>
      ))}

      <Text style={s.section}>打样结论记录</Text>
      <Text style={s.hint}>
        1. 摄像头扫码：能扫出 Code 128 箱码？耗时多少？{'\n'}
        2. 键盘楔入：激光头扫一次，平均按键间隔是否 &lt; 50ms？{'\n'}
        3. 断网后扫码是否仍入队、恢复网络后是否补传成功？{'\n'}
        4. 屏幕尺寸下扫码框与按钮是否够大、戴手套能否点中？
      </Text>
    </ScrollView>
  )
}

const s = StyleSheet.create({
  wrap: { padding: 16, paddingTop: 24, backgroundColor: '#f4f7fb', flexGrow: 1 },
  title: { fontSize: 20, fontWeight: '700', color: '#12263a' },
  hint: { color: '#8494a3', fontSize: 12, marginTop: 6, lineHeight: 19 },
  btn: {
    backgroundColor: '#1891ff', borderRadius: 6, paddingVertical: 12, alignItems: 'center',
    marginTop: 12,
  },
  btnGhost: { backgroundColor: '#fff', borderWidth: 1, borderColor: '#1891ff', marginTop: 8 },
  btnText: { color: '#fff', fontWeight: '600' },
  verdict: { marginTop: 16, fontWeight: '600' },
  okText: { color: '#18a058' },
  warnText: { color: '#d03050' },
  row: {
    flexDirection: 'row', backgroundColor: '#fff', borderRadius: 8, padding: 12,
    marginTop: 8, borderWidth: 1, borderColor: '#e9eef4',
  },
  mark: { width: 22, fontSize: 16, fontWeight: '700' },
  pass: { color: '#18a058' },
  fail: { color: '#d03050' },
  skip: { color: '#a6b0ba' },
  name: { fontWeight: '600', color: '#12263a' },
  detail: { color: '#6b7b8a', fontSize: 12, marginTop: 2 },
  section: { marginTop: 20, marginBottom: 6, fontWeight: '600', color: '#12263a' },
})
