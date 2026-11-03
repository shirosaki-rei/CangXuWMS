import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native'
import { NavigationContainer } from '@react-navigation/native'
import { createNativeStackNavigator } from '@react-navigation/native-stack'
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'
import { StatusBar } from 'expo-status-bar'

import LoginScreen from './src/screens/LoginScreen'
import WorkbenchScreen from './src/screens/WorkbenchScreen'
import ScanScreen from './src/screens/ScanScreen'
import QueueScreen from './src/screens/QueueScreen'
import DiagnosticsScreen from './src/screens/DiagnosticsScreen'
import { initQueue } from './src/db/queue'
import {
  SessionContext, clearSession, loadStored, persistApiBase,
  type Session, type SessionState,
} from './src/stores/session'

const Stack = createNativeStackNavigator()
const Tab = createBottomTabNavigator()

function Tabs() {
  return (
    <Tab.Navigator screenOptions={{ headerShown: false }}>
      <Tab.Screen name="工作台" component={WorkbenchScreen} />
      <Tab.Screen name="扫码" component={ScanScreen} />
      <Tab.Screen name="待同步" component={QueueScreen} />
      <Tab.Screen name="诊断" component={DiagnosticsScreen} />
    </Tab.Navigator>
  )
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [ready, setReady] = useState(false)
  const stateRef = useRef<Session | null>(null)

  useEffect(() => {
    void (async () => {
      await initQueue()
      const s = await loadStored()
      stateRef.current = s
      setSession(s)
      setReady(true)
    })()
  }, [])

  const signIn = useCallback(async (s: Session) => {
    stateRef.current = s
    setSession(s)
  }, [])

  const signOut = useCallback(async () => {
    await clearSession()
    stateRef.current = null
    setSession(null)
  }, [])

  const setApiBase = useCallback(async (base: string) => {
    await persistApiBase(base)
    const cur = stateRef.current
    if (cur) {
      const next = { ...cur, apiBase: base }
      stateRef.current = next
      setSession(next)
    }
  }, [])

  const ctx = useMemo<SessionState>(
    () => ({ session, ready, signIn, signOut, setApiBase }),
    [session, ready, signIn, signOut, setApiBase],
  )

  if (!ready) {
    return (
      <View style={styles.boot}>
        <ActivityIndicator />
        <Text style={styles.bootText}>正在初始化本地队列…</Text>
      </View>
    )
  }

  return (
    <SessionContext.Provider value={ctx}>
      <StatusBar style="dark" />
      <NavigationContainer>
        <Stack.Navigator screenOptions={{ headerShown: false }}>
          {session ? (
            <Stack.Screen name="Main" component={Tabs} />
          ) : (
            <Stack.Screen name="Login" component={LoginScreen} />
          )}
        </Stack.Navigator>
      </NavigationContainer>
    </SessionContext.Provider>
  )
}

const styles = StyleSheet.create({
  boot: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#f4f7fb' },
  bootText: { color: '#8494a3', marginTop: 10, fontSize: 13 },
})
