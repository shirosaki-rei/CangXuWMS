<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { ROLES, systemApi, type UserRow } from '@/api/system'
import { baseDataApi, type Warehouse } from '@/api/basedata'
import { useUserStore } from '@/stores/user'

const user = useUserStore()
const loading = ref(false)
const rows = ref<UserRow[]>([])
const warehouses = ref<Warehouse[]>([])
const query = reactive({ keyword: '', role: '', status: '' })

const dialog = reactive({ visible: false, editing: 0, saving: false })
const form = reactive({
  username: '',
  name: '',
  password: '',
  phone: '',
  role: 'KEEPER',
})
const formRef = ref<FormInstance>()
const rules: FormRules = {
  username: [{ required: true, min: 2, max: 32, message: '2–32 位账号', trigger: 'blur' }],
  name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  password: [{ required: true, min: 6, max: 64, message: '密码至少 6 位', trigger: 'blur' }],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

const roleDlg = reactive({ visible: false, saving: false, uid: 0, username: '', role: 'KEEPER', warehouse_ids: [] as number[] })

/** 需要分配数据权限的角色（主管/管理员/集成账号见全部仓库） */
const NEED_WAREHOUSE = ['KEEPER', 'INSPECTOR']

async function load() {
  loading.value = true
  try {
    rows.value = await systemApi.users({
      keyword: query.keyword || undefined,
      role: query.role || undefined,
      status: query.status || undefined,
    })
  } finally {
    loading.value = false
  }
}

function openCreate() {
  dialog.editing = 0
  Object.assign(form, { username: '', name: '', password: '', phone: '', role: 'KEEPER' })
  dialog.visible = true
}
function openEdit(row: UserRow) {
  dialog.editing = row.id
  Object.assign(form, {
    username: row.username,
    name: row.name,
    password: '',
    phone: row.phone ?? '',
    role: row.role,
  })
  dialog.visible = true
}

async function save() {
  await formRef.value?.validate()
  dialog.saving = true
  try {
    if (dialog.editing) {
      const body: Record<string, unknown> = { name: form.name, phone: form.phone || undefined }
      if (form.password) body.password = form.password
      await systemApi.updateUser(dialog.editing, body)
      ElMessage.success('已保存')
    } else {
      await systemApi.createUser({ ...form })
      ElMessage.success('账号已创建')
    }
    dialog.visible = false
    load()
  } finally {
    dialog.saving = false
  }
}

async function toggleStatus(row: UserRow) {
  const next = row.status === 'ENABLED' ? 'DISABLED' : 'ENABLED'
  if (next === 'DISABLED') {
    await ElMessageBox.confirm(`确认停用账号「${row.username}」？停用后无法登录。`, '停用确认', {
      type: 'warning',
    })
  }
  await systemApi.updateUser(row.id, { status: next })
  ElMessage.success(next === 'ENABLED' ? '已启用' : '已停用')
  load()
}

function openRoles(row: UserRow) {
  roleDlg.uid = row.id
  roleDlg.username = row.username
  roleDlg.role = row.role
  roleDlg.warehouse_ids = [...row.warehouse_ids]
  roleDlg.visible = true
}

async function saveRoles() {
  if (NEED_WAREHOUSE.includes(roleDlg.role) && !roleDlg.warehouse_ids.length) {
    ElMessage.warning('仓管员 / 检验员必须至少分配一个可见仓库')
    return
  }
  roleDlg.saving = true
  try {
    await systemApi.assignRoles(roleDlg.uid, {
      role: roleDlg.role,
      warehouse_ids: roleDlg.warehouse_ids,
    })
    ElMessage.success('权限已更新')
    roleDlg.visible = false
    load()
  } finally {
    roleDlg.saving = false
  }
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  warehouses.value = await baseDataApi.warehouses()
  load()
})
</script>

<template>
  <div>
    <h2 class="panel-title">账号管理</h2>

    <div class="toolbar">
      <el-input v-model="query.keyword" placeholder="姓名 / 账号" clearable style="width: 180px" @keyup.enter="load" />
      <el-select v-model="query.role" placeholder="角色" clearable style="width: 150px">
        <el-option v-for="r in ROLES" :key="r.value" :label="r.label" :value="r.value" />
      </el-select>
      <el-select v-model="query.status" placeholder="状态" clearable style="width: 110px">
        <el-option label="启用" value="ENABLED" />
        <el-option label="停用" value="DISABLED" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
      <el-button type="primary" @click="openCreate">新增账号</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe>
      <el-table-column prop="username" label="账号" width="130" class-name="mono" />
      <el-table-column prop="name" label="姓名" width="110" />
      <el-table-column prop="phone" label="手机号" width="130" />
      <el-table-column label="角色" width="110">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ row.role_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="可见仓库" min-width="200">
        <template #default="{ row }">
          <template v-if="row.warehouse_ids.length">
            <el-tag v-for="id in row.warehouse_ids" :key="id" size="small" class="wh-tag">
              {{ warehouses.find((w) => w.id === id)?.name ?? `#${id}` }}
            </el-tag>
          </template>
          <span v-else class="muted">全部仓库</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.status === 'ENABLED' ? 'success' : 'info'" size="small">
            {{ row.status === 'ENABLED' ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="primary" @click="openRoles(row)">权限</el-button>
          <el-button link :type="row.status === 'ENABLED' ? 'danger' : 'success'" @click="toggleStatus(row)">
            {{ row.status === 'ENABLED' ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog.visible" :title="dialog.editing ? '编辑账号' : '新增账号'" width="440px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="72px">
        <el-form-item label="账号" prop="username">
          <el-input v-model="form.username" :disabled="!!dialog.editing" maxlength="32" />
        </el-form-item>
        <el-form-item label="姓名" prop="name">
          <el-input v-model="form.name" maxlength="64" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="dialog.editing ? '留空表示不修改' : '至少 6 位'"
            maxlength="64"
          />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" maxlength="20" />
        </el-form-item>
        <el-form-item v-if="!dialog.editing" label="角色" prop="role">
          <el-select v-model="form.role" style="width: 100%">
            <el-option v-for="r in ROLES" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="roleDlg.visible" :title="`分配权限 — ${roleDlg.username}`" width="440px">
      <el-form label-width="90px">
        <el-form-item label="角色">
          <el-select v-model="roleDlg.role" style="width: 100%">
            <el-option v-for="r in ROLES" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="可见仓库">
          <el-select
            v-model="roleDlg.warehouse_ids"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="主管 / 管理员 / 集成账号见全部仓库"
            style="width: 100%"
          >
            <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <p class="muted">修改后立即生效；仓管员 / 检验员必须至少分配一个仓库。</p>
      <template #footer>
        <el-button @click="roleDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="roleDlg.saving" @click="saveRoles">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.wh-tag { margin: 2px 4px 2px 0; }
</style>
