import os
import pickle
from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)

# 获取脚本当前所在的目录
current_directory = os.path.dirname(os.path.abspath(__file__))

# 配置相对路径
user_datas_path = os.path.join(current_directory, "user_datas.pkl")
user_info_path = os.path.join(current_directory, "user_info.pkl")

# 加载用户数据
def load_user_datas():
    if os.path.exists(user_datas_path):
        with open(user_datas_path, "rb") as f:
            return pickle.load(f)
    return {}

# 保存用户数据
def save_user_datas(data):
    with open(user_datas_path, "wb") as f:
        pickle.dump(data, f)

# 加载管理员和黑白名单数据
def load_user_info():
    if os.path.exists(user_info_path):
        with open(user_info_path, "rb") as f:
            return pickle.load(f)
    return {}

# 删除用户数据
@app.route("/api/user_datas/<user_id>", methods=["DELETE"])
def delete_user_data(user_id):
    try:
        # 加载现有数据
        user_datas = load_user_datas()
        if user_id in user_datas:
            del user_datas[user_id]  # 删除指定的用户数据
            save_user_datas(user_datas)  # 保存修改后的数据
            return jsonify({"status": "success", "message": f"User {user_id} deleted successfully"})
        else:
            return jsonify({"status": "error", "message": f"User {user_id} not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# 处理不同格式的日期
def format_date(date_str):
    date_formats = [
        '%a, %d %b %Y %H:%M:%S GMT',  # GMT 格式
        '%Y/%m/%d %H:%M:%S',           # YYYY/MM/DD HH:mm:ss 格式
        '%Y年%m月%d日'                 # 中文的年月日格式
    ]
    
    for date_format in date_formats:
        try:
            return datetime.strptime(date_str, date_format)
        except ValueError:
            continue
    raise ValueError(f"日期格式不正确: {date_str}")

# 将 datetime 格式化为 YYYY/MM/DD HH:MM:SS 格式
def format_to_datetime(date_obj):
    return date_obj.strftime('%Y/%m/%d %H:%M:%S')

# 前端页面渲染
frontend_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>用户数据管理界面-MJ</title>
    <link href="https://unpkg.com/tabulator-tables@6.2.5/dist/css/tabulator_midnight.min.css" rel="stylesheet">  <!-- 使用  主题 -->
    <script src="https://unpkg.com/tabulator-tables@6.2.5/dist/js/tabulator.min.js"></script>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css">
    <script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>
    <style>
        /* 页面背景设置为深灰色 */
        body {
            background-color: #333; /* 深灰色背景 */
            color: #fff; /* 字体颜色为白色，确保对比度 */
            font-family: Arial, sans-serif;
            font-size: 16px; /* 默认字体大小 */
            overflow-x: hidden; /* 禁止页面级别的横向滚动 */
        }

        /* 页面全局居中 */
        body, h1, p {
            text-align: center;
        }

        /* 初始页面加载时，隐藏表格内容 */
        #content {
            display: none;
        }

        /* 密码输入框居中 */
        #password-form {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100vh;
        }

        /* 表格外层容器，设置横向滚动 */
        #table-container {
            overflow-x: auto; /* 横向滚动 */
            width: 100%; /* 占满页面宽度 */
            margin: 20px auto;
        }

        /* 表格大小及样式 */
        #user-table {
            min-width: 1000px; /* 设置表格的最小宽度，超出屏幕时可以滑动 */
            margin: 20px auto;
            text-align: center; /* 全局居中 */
            vertical-align: middle; /* 单元格内文本垂直居中 */
        }

        .tabulator .tabulator-cell {
            white-space: pre-wrap; /* 允许文本换行 */
            text-align: center; /* 单元格内文本居中 */
            vertical-align: middle; /* 单元格内文本垂直居中 */
            font-size: 14px; /* 单元格字体大小 */
        }

        .tabulator .tabulator-header {
            text-align: center; /* 标题文本居中 */
            vertical-align: middle; /* 单元格内文本垂直居中 */
            background-color: #444;
            color: #fff;
        }

        /* 针对移动设备的优化 */
        @media (max-width: 768px) {
            body {
                font-size: 14px; /* 手机端调整字体大小 */
            }
            .tabulator {
                font-size: 12px; /* 调整表格字体大小 */
                height: auto; /* 移动设备上表格高度自适应 */
            }
            .tabulator .tabulator-cell {
                font-size: 12px;
                white-space: normal; /* 手机端自动换行 */
            }
            #user-table {
                min-width: 1000px; /* 保持表格宽度，支持横向滚动 */
            }
        }

        /* 单元格颜色 */
        .admin-cell-yes {
            background-color: blue; /* 管理员标记蓝色 */
        }

        .whitelist-cell-yes {
            background-color: green; /* 白名单标记绿色 */
        }

        .blacklist-cell-yes {
            background-color: red; /* 黑名单标记红色 */
        }
    </style>

</head>
<body>

    <!-- 密码输入框 -->
    <div id="password-form">
        <h1>Enter dddd to Access</h1>
        <input type="password" id="password" placeholder="Enter dddd" />
        <h1> </h1>
        <button onclick="checkPassword()">Submit</button>
        <p id="error-msg" style="color: red; display: none;">Incorrect password. Please try again.</p>
    </div>

    <!-- 受保护的页面内容 -->
    <div id="content">
        <h1>请谨慎操作，提交后不可逆!</h1>
        <p>由于画图程序正在运行，为确保准确，数据将在 <span id="countdown">15</span> 秒后更新，若有修改请及时提交。</p>
        
        <!-- 表格区域 -->
        <div id="table-container">
            <div id="user-table"></div>
        </div>
        <button onclick="saveData()">Save Changes</button>
    </div>

    <script>
        let countdownInterval;  // 倒计时间隔的变量
        const countdownTime = 15; // 倒计时时间（秒）

        // 设置并启动倒计时
        function startCountdown() {
            let countdown = countdownTime;
            document.getElementById('countdown').innerText = countdown;

            clearInterval(countdownInterval);  // 清除之前的倒计时（如果存在）

            countdownInterval = setInterval(function() {
                countdown--;
                document.getElementById('countdown').innerText = countdown;

                if (countdown <= 0) {
                    clearInterval(countdownInterval);  // 停止倒计时
                    loadTable();  // 加载新的表格数据
                    startCountdown();  // 重置倒计时
                }
            }, 1000);  // 每秒执行一次
        }
    
        // 设定正确的密码
        const correctPassword = "password";

        // 验证用户输入的密码
        function checkPassword() {
            const inputPassword = document.getElementById('password').value;
            const errorMsg = document.getElementById('error-msg');

            // 检查密码是否正确
            if (inputPassword === correctPassword) {
                // 如果正确，显示表格内容，隐藏密码输入框
                document.getElementById('content').style.display = 'block';
                document.getElementById('password-form').style.display = 'none';
                loadTable(); // 加载表格数据
                startCountdown(); // 开始倒计时
            } else {
                // 如果错误，显示错误消息
                errorMsg.style.display = 'block';
            }
        }

        let table;  // 全局声明表格实例

        // 使用 Flatpickr 作为日期编辑器
        function dateEditor(cell, onRendered, success, cancel) {
            var editor = document.createElement("input");
            editor.setAttribute("type", "text");
            editor.style.width = "100%";

            // 选择日期时，启用移动友好模式
            flatpickr(editor, {
                enableTime: true,  // 启用时间选择
                dateFormat: "Y/m/d H:i:S",  // 自定义日期格式
                defaultDate: cell.getValue(),  // 设定当前单元格值为默认日期
                onClose: function(selectedDates, dateStr, instance) {
                    success(dateStr);  // 用户选择日期后提交
                },
                disableMobile: false,  // 允许移动设备使用原生选择器（如iOS日期选择器）
            });

            onRendered(function() {
                editor.focus();
            });

            return editor;
        }

        // 表格加载与数据展示
        function loadTable() {
            fetch('/api/user_datas')
                .then(response => response.json())
                .then(data => {
                    // 将字典转换为数组，用于 Tabulator 显示
                    const tableData = Object.entries(data).map(([key, value]) => {
                        const mj_data = value.mj_datas;
                        return { 
                            user_id: key, 
                            nickname: mj_data.nickname,
                            isgroup: mj_data.isgroup,
                            group_name: mj_data.group_name || "None", // 如果没有 group_name，则显示 None
                            default_limit: mj_data.default_limit,
                            limit: mj_data.limit,
                            expire_time: mj_data.expire_time, 
                            update_time: mj_data.update_time,
                            is_admin: value.is_admin ? "Yes" : "No", 
                            is_in_blacklist: value.is_in_blacklist ? "Yes" : "No",
                            is_in_whitelist: value.is_in_whitelist ? "Yes" : "No",
                            is_in_blackgroup: value.is_in_blackgroup ? "Yes" : "No",
                            is_in_whitegroup: value.is_in_whitegroup ? "Yes" : "No"
                        };
                    });

                    // 如果表格已经初始化，则更新数据
                    if (table) {
                        table.setData(tableData);
                    } else {
                        // 初始化 Tabulator 表格，并将实例保存在全局的 `table` 变量中
                        table = new Tabulator("#user-table", {
                            data: tableData,
                            layout: "fitColumns",  // 自适应宽度
                            responsiveLayout: true,  // 响应式布局
                            pagination: "local",  // 本地分页
                            paginationSize: 10,  // 每页显示10行
                            columns: [
                                { title: "操作", formatter: deleteButton, width: 100, align: "center", headerHozAlign: "center" },
                                { title: "昵称", field: "nickname", headerFilter: "input", align: "center", headerHozAlign: "center" },  // 添加筛选器
                                { title: "群组", field: "group_name", headerFilter: "input", align: "center", headerHozAlign: "center" },  // 添加筛选器
                                { title: "限制", field: "default_limit", headerFilter: "input", editor: "number", align: "center", headerHozAlign: "center" },
                                { title: "剩余", field: "limit", headerFilter: "input", editor: "number", align: "center", headerHozAlign: "center" },
                                { title: "到期时间", field: "expire_time", headerFilter: "input", editor: dateEditor, align: "center", headerHozAlign: "center" },
                                { title: "更新时间", field: "update_time", headerFilter: "input", align: "center", headerHozAlign: "center" },
                                { title: "管理员", field: "is_admin", headerFilter: "input", formatter: formatAdminCell, align: "center", headerHozAlign: "center" },
                                { title: "白用户", field: "is_in_whitelist", headerFilter: "input", formatter: formatWhitelistCell, align: "center", headerHozAlign: "center" },
                                { title: "黑用户", field: "is_in_blacklist", headerFilter: "input", formatter: formatBlacklistCell, align: "center", headerHozAlign: "center" },
                                { title: "白群组", field: "is_in_whitegroup", headerFilter: "input", formatter: formatWhitelistCell, align: "center", headerHozAlign: "center" },
                                { title: "黑群组", field: "is_in_blackgroup", headerFilter: "input", formatter: formatBlacklistCell, align: "center", headerHozAlign: "center" }
                            ]
                        });
                    }
                });
        }

        // 删除按钮格式化器
        function deleteButton(cell, formatterParams) {
            return "<button class='delete-btn'>删除</button>";
        }

        // 删除行功能
        document.addEventListener("click", function(e) {
            if (e.target.classList.contains('delete-btn')) {
                let row = e.target.closest('.tabulator-row');
                let rowData = table.getRow(row).getData();

                // 弹出确认框
                let confirmDelete = confirm("确定要删除此条数据吗？");
                if (confirmDelete) {
                    table.deleteRow(row); // 从表格中删除该行
                    deleteRowData(rowData.user_id); // 调用删除后端数据的函数
                }
            }
        });

        // 调用后端API删除数据
        function deleteRowData(user_id) {
            fetch(`/api/user_datas/${user_id}`, {
                method: 'DELETE'
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                console.log("User data deleted successfully:", data);
                alert("Data deleted successfully");
            })
            .catch(error => {
                console.error('Error during deletion:', error);
                alert('Error during deletion: ' + error);
            });
        }

        // 管理员单元格格式化
        function formatAdminCell(cell, formatterParams) {
            let value = cell.getValue();
            return value === "Yes" ? "<div class='admin-cell-yes'>" + value + "</div>" : value;
        }

        // 白名单单元格格式化
        function formatWhitelistCell(cell, formatterParams) {
            let value = cell.getValue();
            return value === "Yes" ? "<div class='whitelist-cell-yes'>" + value + "</div>" : value;
        }

        // 黑名单单元格格式化
        function formatBlacklistCell(cell, formatterParams) {
            let value = cell.getValue();
            return value === "Yes" ? "<div class='blacklist-cell-yes'>" + value + "</div>" : value;
        }

        // 保存修改后的数据
        function saveData() {
            // 弹出确认框
            let confirmSave = confirm("确定要保存更改吗？");
            if (!confirmSave) {
                return;  // 用户取消保存，直接返回
            }

            if (!table) {
                alert("Table not initialized!");
                return;
            }
            
            let tableData = table.getData();
            console.log("Table data:", tableData);  // 在控制台输出表格数据

            let userDataDict = {};

            // 构建要发送的 userDataDict
            tableData.forEach(row => {
                userDataDict[row.user_id] = {
                    mj_datas: {
                        nickname: row.nickname,
                        isgroup: row.isgroup,
                        group_name: row.group_name,
                        default_limit: row.default_limit,
                        limit: row.limit,
                        expire_time: row.expire_time,
                        update_time: row.update_time
                    }
                };
            });

            console.log("Sending data to server:", userDataDict);  // 在控制台输出要发送的数据

            fetch('/api/user_datas', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(userDataDict)
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                console.log("Response from server:", data);  // 打印服务器响应
                alert("Data saved successfully");
            })
            .catch(error => {
                console.error('Error during fetch request:', error);  // 捕获 fetch 请求错误
                alert('Error during fetch request: ' + error);
            });
        }
    </script>

</body>
</html>
"""

@app.route("/")
def index():
    # 提供前端页面
    return render_template_string(frontend_html)

@app.route("/api/user_datas", methods=["GET"])
def get_user_datas():
    # 获取 user_datas 数据
    user_datas = load_user_datas()
    user_info = load_user_info()  # 加载管理员和黑白名单数据
    
    # 合并用户数据和黑白名单数据
    for key, value in user_datas.items():
        user_id = key.split('_')[0]  # 提取 user_id
        
        # 标记是否是管理员
        value['is_admin'] = any(admin.get('user_id') == user_id for admin in user_info.get('mj_admin_users', []))
        
        # 标记是否在黑/白名单和群组
        value['is_in_blacklist'] = user_id in user_info.get('mj_busers', [])
        value['is_in_whitelist'] = user_id in user_info.get('mj_users', [])
        value['is_in_blackgroup'] = value['mj_datas'].get('group_name') in user_info.get('mj_bgroups', [])
        value['is_in_whitegroup'] = value['mj_datas'].get('group_name') in user_info.get('mj_groups', [])

    return jsonify(user_datas)

@app.route("/api/user_datas", methods=["POST"])
def update_user_datas():
    try:
        # 获取从前端传来的数据
        data = request.json
        print("Received data from frontend:", data)  # 打印接收到的数据

        # 加载当前数据，更新为前端传递的数据
        current_data = load_user_datas()
        print("Current data before update:", current_data)  # 打印现有数据

        # 遍历前端传递过来的数据，更新或插入现有数据
        for user_id, value in data.items():
            current_data[user_id] = value  # 直接更新或插入数据

        print("Updated data:", current_data)  # 打印更新后的数据

        # 保存更新后的数据
        save_user_datas(current_data)
        print("Data successfully saved!")  # 成功保存后的提示

        return jsonify({"status": "success"})
    except Exception as e:
        # 打印任何发生的异常
        print(f"Error occurred while processing POST request: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
