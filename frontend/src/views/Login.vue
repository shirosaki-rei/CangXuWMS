<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { authApi } from '@/api/auth'
import { useUserStore } from '@/stores/user'
import BrandMark from '@/components/BrandMark.vue'

const route = useRoute()
const router = useRouter()
const user = useUserStore()

const loading = ref(false)
const captchaImg = ref('')
const form = reactive({ username: '', password: '', captcha: '' })
const rules: FormRules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
  captcha: [{ required: true, min: 4, max: 4, message: '请输入 4 位验证码', trigger: 'blur' }],
}
const formRef = ref<FormInstance>()
let captchaId = ''

async function refreshCaptcha() {
  const c = await authApi.captcha()
  captchaId = c.captcha_id
  captchaImg.value = c.image
  form.captcha = ''
}

async function onSubmit() {
  await formRef.value?.validate()
  loading.value = true
  try {
    const r = await authApi.login({ ...form, captcha_id: captchaId })
    user.setTokens(r.access_token, r.refresh_token)
    await user.loadMe()
    ElMessage.success(`欢迎，${r.user.name}`)
    router.replace((route.query.redirect as string) || r.landing || '/dashboard')
  } catch {
    refreshCaptcha() // 失败必须换验证码，否则会被一次性校验挡住
  } finally {
    loading.value = false
  }
}

refreshCaptcha()
</script>

<template>
  <div class="login-wrap">
    <div class="login-box">
      <div class="login-hd">
        <div class="login-logo"><BrandMark :size="30" /></div>
        <div>
          <h1>仓序 WMS</h1>
          <p>仓储管理系统</p>
        </div>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="onSubmit">
        <el-form-item label="账号" prop="username">
          <el-input v-model="form.username" placeholder="请输入账号" size="large" autofocus />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="请输入密码" size="large" />
        </el-form-item>
        <el-form-item label="验证码" prop="captcha">
          <div class="cap-row">
            <el-input v-model="form.captcha" placeholder="4 位字符" size="large" maxlength="4" />
            <img v-if="captchaImg" :src="captchaImg" class="cap-img" title="点击刷新" @click="refreshCaptcha" />
          </div>
        </el-form-item>
        <el-button type="primary" size="large" class="login-btn" :loading="loading" @click="onSubmit">
          登 录
        </el-button>
      </el-form>

      <p class="login-tip">连续 5 次密码错误将锁定账号 10 分钟</p>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0d5bb5 0%, #1891ff 55%, #6ec2ff 100%);
}
.login-box {
  width: 380px;
  background: #fff;
  border-radius: 6px;
  padding: 30px 32px 24px;
  box-shadow: 0 12px 40px rgba(6, 40, 80, 0.28);
}
.login-hd { display: flex; align-items: center; gap: 12px; margin-bottom: 22px; }
.login-logo {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  background: #eaf3ff;
  color: var(--blue);
  display: flex;
  align-items: center;
  justify-content: center;
}
.login-hd h1 { font-size: 18px; margin: 0; color: #1b2b3a; }
.login-hd p { margin: 2px 0 0; font-size: 11px; color: #9aa4af; letter-spacing: 0.5px; }
.cap-row { display: flex; gap: 10px; width: 100%; }
.cap-row .el-input { flex: 1; }
.cap-img {
  width: 120px;
  height: 40px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  cursor: pointer;
  background: #f4f7fb;
}
.login-btn { width: 100%; margin-top: 6px; letter-spacing: 4px; }
.login-tip { text-align: center; color: #a6b0ba; font-size: 11px; margin: 14px 0 0; }
</style>
