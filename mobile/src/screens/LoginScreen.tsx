import { useEffect, useState } from 'react'
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native'
import { SvgXml } from 'react-native-svg'
import { request } from '../api/client'
import { DEFAULT_API_BASE } from '../config'
import { saveSession, useSession } from '../stores/session'

interface Captcha { captcha_id: string; image: string; ttl: number }

/** 后端返回的是 SVG data URI；RN 的 <Image> 不认 SVG，解码后用 SvgXml 渲染 */
function svgFromDataUri(uri: string): string {
  const b64 = uri.split(',')[1] ?? ''
  return globalThis.atob ? globalThis.atob(b64) : ''
}

export default function LoginScreen() {
  const { signIn } = useSession()
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [captcha, setCaptcha] = useState('')
  const [cap, setCap] = useState<Captcha | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function refreshCaptcha(base = apiBase) {
    try {
      const r = await request<Captcha>({ base, path: '/auth/captcha' })
      setCap(r.data)
      setCaptcha('')
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  useEffect(() => { void refreshCaptcha() }, [])

  async function submit() {
    if (!cap) return
    setBusy(true)
    setErr('')
    try {
      const r = await request<{
        access_token: string
        user: { name: string; role: string; warehouses: { id: number; name: string }[] }
      }>({
        base: apiBase,
        method: 'POST',
        path: '/auth/login',
        body: {
          username, password,
          captcha_id: cap.captcha_id,
          captcha,
        },
      })
      await signIn({
        token: r.data.access_token,
        apiBase,
        name: r.data.user.name,
        role: r.data.user.role,
        warehouses: r.data.user.warehouses,
      })
      await saveSession({
        token: r.data.access_token,
        apiBase,
        name: r.data.user.name,
        role: r.data.user.role,
        warehouses: r.data.user.warehouses,
      })
    } catch (e) {
      setErr((e as Error).message)
      void refreshCaptcha()
    } finally {
      setBusy(false)
    }
  }

  return (
    <ScrollView contentContainerStyle={s.wrap} keyboardShouldPersistTaps="handled">
      <Text style={s.title}>仓序 WMS</Text>
      <Text style={s.sub}>仓储作业端</Text>

      <Text style={s.label}>服务器地址</Text>
      <TextInput
        style={s.input}
        value={apiBase}
        onChangeText={setApiBase}
        autoCapitalize="none"
        autoCorrect={false}
        placeholder="http://192.168.1.20:8000/api/v1"
        onEndEditing={() => refreshCaptcha(apiBase)}
      />

      <Text style={s.label}>账号</Text>
      <TextInput style={s.input} value={username} onChangeText={setUsername} autoCapitalize="none" />

      <Text style={s.label}>密码</Text>
      <TextInput style={s.input} value={password} onChangeText={setPassword} secureTextEntry />

      <Text style={s.label}>验证码</Text>
      <View style={s.capRow}>
        <TextInput
          style={[s.input, { flex: 1 }]}
          value={captcha}
          onChangeText={setCaptcha}
          maxLength={4}
          autoCapitalize="characters"
        />
        <Pressable style={s.capBox} onPress={() => refreshCaptcha()}>
          {cap ? (
            <SvgXml xml={svgFromDataUri(cap.image)} width={110} height={36} />
          ) : null}
        </Pressable>
      </View>

      {!!err && <Text style={s.err}>{err}</Text>}

      <Pressable style={[s.btn, busy && { opacity: 0.6 }]} onPress={submit} disabled={busy}>
        {busy ? <ActivityIndicator color="#fff" /> : <Text style={s.btnText}>登 录</Text>}
      </Pressable>

      <Text style={s.hint}>连续 5 次密码错误将锁定账号 10 分钟</Text>
    </ScrollView>
  )
}

const s = StyleSheet.create({
  wrap: { padding: 24, paddingTop: 64, backgroundColor: '#f4f7fb', flexGrow: 1 },
  title: { fontSize: 28, fontWeight: '700', color: '#0d5bb5' },
  sub: { color: '#7b8a99', marginBottom: 24, marginTop: 4 },
  label: { color: '#5b6b7a', fontSize: 13, marginBottom: 6, marginTop: 12 },
  input: {
    backgroundColor: '#fff', borderWidth: 1, borderColor: '#dde2e8', borderRadius: 6,
    paddingHorizontal: 12, paddingVertical: 10, fontSize: 15,
  },
  capRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  capBox: {
    width: 118, height: 42, backgroundColor: '#fff', borderWidth: 1, borderColor: '#dde2e8',
    borderRadius: 6, alignItems: 'center', justifyContent: 'center',
  },
  btn: {
    marginTop: 24, backgroundColor: '#1891ff', borderRadius: 6, paddingVertical: 14,
    alignItems: 'center',
  },
  btnText: { color: '#fff', fontSize: 16, fontWeight: '600', letterSpacing: 4 },
  err: { color: '#d03050', marginTop: 12 },
  hint: { color: '#a6b0ba', fontSize: 12, textAlign: 'center', marginTop: 14 },
})
