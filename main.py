from flask import Flask, render_template_string, request, redirect, url_for

app = Flask(__name__)

# ゲーム状態管理
game_state = {
    'turn': 1,
    'history': [],  # [{'turn': 1, 'player_name': '...', 'type': 'text'/'image', 'content': '...'}, ...]
    'is_finished': False
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>テレストレーションwebs</title>
</head>
<body>
    <h1>テレストレーション゙web</h1>
    <hr>

    {% if game_state.is_finished %}
        <!-- 5ターン終了時の中間発表画面 -->
        <h2> 5ターン達成！ 中間発表タイム </h2>
        
        </p>

        <table border="1" cellpadding="10">
            <tr>
                <th>ターン</th>
                <th>プレイヤー</th>
                <th>種類</th>
                <th>伝言内容</th>
            </tr>
            {% for item in game_state.history %}
            <tr>
                <td align="center">第 {{ item.turn }} ターン</td>
                <td align="center"><strong>{{ item.player_name }}</strong> さん</td>
                <td align="center">
                    {% if item.type == 'text' %}お題 (文字){% else %}お絵描き (絵){% endif %}
                </td>
                <td align="center">
                    {% if item.turn == 5 %}
                        <!-- CSS (display) を利用した表示・非表示エリア -->
                        <div id="spoiler-mask">
                            <h3> 【？？？？？】<br><small>(最後の絵を観て書いたお題)</small></h3>
                        </div>
                        <div id="spoiler-content" style="display: none;">
                            <h2>{{ item.content }}</h2>
                        </div>
                    {% else %}
                        {% if item.type == 'text' %}
                            <h2>{{ item.content }}</h2>
                        {% else %}
                            <img src="{{ item.content }}" width="350">
                        {% endif %}
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </table>
        <br>

        <!-- ボタンで即座に非表示を解除 -->
        <div id="reveal-button-container">
            <button type="button" onclick="showLastAnswer()"> 最後の回答（第5ターンのお題）をオープンして爆笑する！</button>
        </div>

        <script>
            function showLastAnswer() {
                // CSSのdisplayプロパティを切り替えて即座にオープン
                document.getElementById('spoiler-mask').style.display = 'none';
                document.getElementById('spoiler-content').style.display = 'block';
                document.getElementById('reveal-button-container').style.display = 'none';
            }
        </script>

        <br><hr>
        <form action="/reset" method="post">
            <button type="submit">新しいゲーム（第1ターンから）を始める</button>
        </form>

    {% else %}
        <!-- 進行中の画面 -->
        <h2>現在の状態: 第 {{ game_state.turn }} / 5 ターン</h2>

        {% if game_state.turn == 1 %}
            <h3>【第1ターン：お題作成】</h3>
            <p>最初のお題と、あなたの名前を入力してください！</p>
            <form action="/submit" method="post">
                <p>プレイヤー名: <input type="text" name="player_name" placeholder="名前（例: たろう）" required autofocus></p>
                <p>お題: <input type="text" name="text_content" placeholder="お題（例: ゴリラ）" required></p>
                <button type="submit">お題を決定して次の人へ</button>
            </form>

        {% elif game_state.turn == 2 or game_state.turn == 4 %}
            <h3>【第{{ game_state.turn }}ターン：お絵描き】</h3>
            <p>前のお題を見て、下に絵を描いてください！</p>
            <p><strong>前のお題：</strong></p>
            <h2>「 {{ previous_content }} 」</h2>

            <form id="drawForm" action="/submit" method="post">
                <p>プレイヤー名: <input type="text" name="player_name" placeholder="名前（例: はなこ）" required></p>

                <p>【キャンバス】（マウスまたはタッチ操作で描いてください）</p>
                <table border="1">
                    <tr>
                        <td>
                            <canvas id="paintCanvas" width="400" height="300"></canvas>
                        </td>
                    </tr>
                </table>
                <br>
                <button type="button" onclick="clearCanvas()">描き直す（クリア）</button>
                <br><br>
                <input type="hidden" name="image_content" id="image_content">
                <button type="button" onclick="submitDrawing()">描いた絵を送信して次の人へ</button>
            </form>

            <script>
                var canvas = document.getElementById('paintCanvas');
                var ctx = canvas.getContext('2d');
                var isDrawing = false;

                ctx.fillStyle = "#ffffff";
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.lineWidth = 4;
                ctx.lineCap = "round";
                ctx.strokeStyle = "#000000";

                function getPos(e) {
                    var rect = canvas.getBoundingClientRect();
                    var clientX = e.clientX || (e.touches && e.touches[0].clientX);
                    var clientY = e.clientY || (e.touches && e.touches[0].clientY);
                    return {
                        x: clientX - rect.left,
                        y: clientY - rect.top
                    };
                }

                function startDrawing(e) {
                    isDrawing = true;
                    var pos = getPos(e);
                    ctx.beginPath();
                    ctx.moveTo(pos.x, pos.y);
                }

                function draw(e) {
                    if (!isDrawing) return;
                    var pos = getPos(e);
                    ctx.lineTo(pos.x, pos.y);
                    ctx.stroke();
                }

                function stopDrawing() {
                    isDrawing = false;
                }

                canvas.addEventListener('mousedown', startDrawing);
                canvas.addEventListener('mousemove', draw);
                canvas.addEventListener('mouseup', stopDrawing);
                canvas.addEventListener('mouseleave', stopDrawing);

                canvas.addEventListener('touchstart', function(e) { startDrawing(e); e.preventDefault(); });
                canvas.addEventListener('touchmove', function(e) { draw(e); e.preventDefault(); });
                canvas.addEventListener('touchend', stopDrawing);

                function clearCanvas() {
                    ctx.fillStyle = "#ffffff";
                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                }

                function submitDrawing() {
                    var form = document.getElementById('drawForm');
                    if (!form.checkValidity()) {
                        form.reportValidity();
                        return;
                    }
                    var dataURL = canvas.toDataURL('image/png');
                    document.getElementById('image_content').value = dataURL;
                    form.submit();
                }
            </script>

        {% elif game_state.turn == 3 or game_state.turn == 5 %}
            <h3>【第{{ game_state.turn }}ターン：お題当て】</h3>
            <p>前の絵を見て、何が描かれているかお題を当ててください！</p>
            <p><strong>前の絵：</strong></p>
            <p><img src="{{ previous_content }}" border="1" width="400"></p>

            <form action="/submit" method="post">
                <p>プレイヤー名: <input type="text" name="player_name" placeholder="名前（例: じんたろう）" required autofocus></p>
                <p>予想したお題: <input type="text" name="text_content" placeholder="予想したお題を入力" required></p>
                <button type="submit">予想を送信する</button>
            </form>
        {% endif %}

        <br><hr>
        <form action="/reset" method="post" onsubmit="return confirm('本当に最初からやり直しますか？');">
            <button type="submit">ゲームをリセット</button>
        </form>
    {% endif %}
</body>
</html>
"""

@app.route('/')
def index():
    prev_content = None
    if game_state['history']:
        prev_content = game_state['history'][-1]['content']
    return render_template_string(HTML_TEMPLATE, game_state=game_state, previous_content=prev_content)

@app.route('/submit', methods=['POST'])
def submit():
    turn = game_state['turn']
    player_name = request.form.get('player_name', '名無し')
    
    if turn in [1, 3, 5]:
        content = request.form.get('text_content')
        game_state['history'].append({
            'turn': turn,
            'player_name': player_name,
            'type': 'text',
            'content': content
        })
    elif turn in [2, 4]:
        content = request.form.get('image_content')
        game_state['history'].append({
            'turn': turn,
            'player_name': player_name,
            'type': 'image',
            'content': content
        })

    if turn >= 5:
        game_state['is_finished'] = True
    else:
        game_state['turn'] += 1

    return redirect(url_for('index'))

@app.route('/reset', methods=['POST'])
def reset():
    game_state['turn'] = 1
    game_state['history'] = []
    game_state['is_finished'] = False
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=8000)



# 固定