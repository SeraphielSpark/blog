import os
from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, make_response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from sqlalchemy import desc
import html

# Initialize Flask app
app = Flask(__name__)

# Configure database
uri = os.getenv("DATABASE_URL")
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri or 'sqlite:///blog.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Generate secret key
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# Initialize database
db = SQLAlchemy(app)

# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    online = db.Column(db.Boolean, default=False)
    last_seen = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_published = db.Column(db.Boolean, default=True)
    author = db.relationship('User', backref=db.backref('posts', lazy=True))

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id'))
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_approved = db.Column(db.Boolean, default=False)
    post = db.relationship('Post', backref=db.backref('comments', lazy=True, order_by=desc(created_at)))
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), lazy=True)

# Context processor for current year
@app.context_processor
def inject_current_year():
    return {'current_year': datetime.utcnow().year}

# Health check endpoint
@app.route('/health')
def health():
    return 'OK', 200

# Initialize admin user
def init_admin():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', online=True)
            admin.set_password(os.environ.get('ADMIN_PASSWORD', 'admin123'))
            db.session.add(admin)
            db.session.commit()

# Routes
@app.route('/')
def home():
    try:
        posts = Post.query.filter_by(is_published=True).order_by(Post.created_at.desc()).all()
        return render_template_string(HOME_TEMPLATE, posts=posts)
    except Exception as e:
        return make_response("Blog is starting up. Please refresh in a moment...", 503)

@app.route('/post/<int:post_id>')
def post_detail(post_id):
    try:
        post = Post.query.get_or_404(post_id)
        comments = Comment.query.filter_by(post_id=post_id, parent_id=None, is_approved=True).order_by(Comment.created_at.desc()).all()
        return render_template_string(POST_DETAIL_TEMPLATE, post=post, comments=comments)
    except Exception as e:
        return make_response("Post not found", 404)

@app.route('/add_comment', methods=['POST'])
def add_comment():
    try:
        data = request.get_json()
        if not data or not all(key in data for key in ['name', 'email', 'content', 'postId']):
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        
        new_comment = Comment(
            post_id=data['postId'],
            parent_id=data.get('parentId'),
            name=html.escape(data['name']),
            email=html.escape(data['email']),
            content=html.escape(data['content'])
        )
        
        db.session.add(new_comment)
        db.session.commit()
        return jsonify({'success': True, 'comment_id': new_comment.id})
    except Exception as e:
        return jsonify({'success': False, 'message': 'Internal server error'}), 500

@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        try:
            username = request.form.get('username')
            password = request.form.get('password')
            user = User.query.filter_by(username=username).first()
            
            if user and user.check_password(password):
                session['user_id'] = user.id
                user.online = True
                user.last_seen = datetime.utcnow()
                db.session.commit()
                return redirect(url_for('admin_dashboard'))
            return render_template_string(ADMIN_LOGIN_TEMPLATE, error='Invalid credentials')
        except Exception as e:
            return render_template_string(ADMIN_LOGIN_TEMPLATE, error='Internal server error')
    return render_template_string(ADMIN_LOGIN_TEMPLATE)

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('admin_login'))
    
    try:
        stats = {
            'total_posts': Post.query.count(),
            'pending_comments': Comment.query.filter_by(is_approved=False).count(),
            'online_users': User.query.filter_by(online=True).count()
        }
        
        recent_posts = Post.query.order_by(Post.created_at.desc()).limit(5).all()
        recent_comments = Comment.query.order_by(Comment.created_at.desc()).limit(5).all()
        
        return render_template_string(ADMIN_DASHBOARD_TEMPLATE, 
                            stats=stats,
                            recent_posts=recent_posts,
                            recent_comments=recent_comments)
    except Exception as e:
        return render_template_string(ADMIN_DASHBOARD_TEMPLATE, error='Database error')

@app.route('/admin/posts', methods=['GET', 'POST'])
def manage_posts():
    if 'user_id' not in session:
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        try:
            post_id = request.form.get('post_id')
            action = request.form.get('action')
            
            if action == 'delete':
                Post.query.filter_by(id=post_id).delete()
            elif action == 'toggle':
                post = Post.query.get(post_id)
                if post:
                    post.is_published = not post.is_published
            
            db.session.commit()
        except Exception as e:
            db.session.rollback()
    
    try:
        posts = Post.query.order_by(Post.created_at.desc()).all()
        return render_template_string(ADMIN_POSTS_TEMPLATE, posts=posts)
    except Exception as e:
        return render_template_string(ADMIN_POSTS_TEMPLATE, error='Database error')

@app.route('/admin/comments', methods=['GET', 'POST'])
def manage_comments():
    if 'user_id' not in session:
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        try:
            comment_id = request.form.get('comment_id')
            action = request.form.get('action')
            
            if action == 'delete':
                Comment.query.filter_by(id=comment_id).delete()
            elif action == 'toggle':
                comment = Comment.query.get(comment_id)
                if comment:
                    comment.is_approved = not comment.is_approved
            
            db.session.commit()
        except Exception as e:
            db.session.rollback()
    
    try:
        comments = Comment.query.order_by(Comment.created_at.desc()).all()
        return render_template_string(ADMIN_COMMENTS_TEMPLATE, comments=comments)
    except Exception as e:
        return render_template_string(ADMIN_COMMENTS_TEMPLATE, error='Database error')

@app.route('/admin/new_post', methods=['GET', 'POST'])
def new_post():
    if 'user_id' not in session:
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        try:
            title = request.form.get('title')
            content = request.form.get('content')
            status = request.form.get('status', 'published')
            
            if not title or not content:
                return render_template_string(ADMIN_NEW_POST_TEMPLATE, error='Title and content are required')
            
            new_post = Post(
                title=html.escape(title),
                content=html.escape(content),
                author_id=session['user_id'],
                is_published=(status == 'published')
            )
            
            db.session.add(new_post)
            db.session.commit()
            return redirect(url_for('manage_posts'))
        except Exception as e:
            return render_template_string(ADMIN_NEW_POST_TEMPLATE, error='Failed to create post')
    
    return render_template_string(ADMIN_NEW_POST_TEMPLATE)

@app.route('/admin/logout')
def admin_logout():
    if 'user_id' in session:
        try:
            user = User.query.get(session['user_id'])
            if user:
                user.online = False
                db.session.commit()
        except Exception as e:
            pass
    session.pop('user_id', None)
    return redirect(url_for('home'))

# HTML Templates
HOME_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>My Awesome Blog</title>
    <style>
        :root {
            --primary: #4361ee;
            --primary-dark: #3a0ca3;
            --secondary: #3f37c9;
            --accent: #4895ef;
            --danger: #f72585;
            --success: #4cc9f0;
            --light: #f8f9fa;
            --dark: #212529;
            --gray: #6c757d;
            --white: #ffffff;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        
        body {
            background-color: #f5f7fb;
            color: var(--dark);
            line-height: 1.6;
        }
        
        .page-container {
            display: flex;
            flex-direction: column;
            min-height: 100vh;
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .main-header {
            background-color: var(--white);
            padding: 1rem 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .header-content {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .main-nav a {
            margin-left: 1.5rem;
            text-decoration: none;
            color: var(--primary);
            font-weight: 500;
        }
        
        .main-content {
            flex: 1;
            padding: 2rem;
        }
        
        .main-footer {
            background-color: var(--dark);
            color: var(--white);
            padding: 1.5rem;
            text-align: center;
        }
        
        .blog-container {
            max-width: 800px;
            margin: 0 auto;
        }
        
        .post-full, .post-preview {
            background-color: var(--white);
            border-radius: 8px;
            padding: 2rem;
            margin-bottom: 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .post-title {
            margin-bottom: 1rem;
            color: var(--dark);
        }
        
        .post-meta {
            color: var(--gray);
            margin-bottom: 1.5rem;
            font-size: 0.9rem;
        }
        
        .post-content {
            margin-bottom: 1.5rem;
            line-height: 1.7;
        }
        
        .comments-section {
            margin-top: 3rem;
            padding-top: 2rem;
            border-top: 1px solid #eee;
        }
        
        .comment {
            background-color: var(--light);
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }
        
        .comment-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 0.5rem;
        }
        
        .btn {
            display: inline-block;
            padding: 0.5rem 1rem;
            background-color: var(--primary);
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            text-decoration: none;
            font-size: 1rem;
        }
        
        .btn:hover {
            background-color: var(--primary-dark);
        }
        
        .form-group {
            margin-bottom: 1rem;
        }
        
        .form-group input,
        .form-group textarea {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 1rem;
        }
        
        .form-group textarea {
            min-height: 150px;
        }
        
        .error-message {
            background-color: #f8d7da;
            color: #721c24;
            padding: 1rem;
            border-radius: 4px;
            margin-bottom: 1.5rem;
        }
        
        @media (max-width: 768px) {
            .header-content {
                flex-direction: column;
                gap: 1rem;
            }
            
            .main-nav {
                display: flex;
                gap: 1rem;
            }
        }
    </style>
</head>
<body>
    <div class="page-container">
        <header class="main-header">
            <div class="header-content">
                <h1><a href="/">My Awesome Blog</a></h1>
                <nav class="main-nav">
                    <a href="/">Home</a>
                    <a href="/admin">Admin</a>
                </nav>
            </div>
        </header>

        <main class="main-content">
            <div class="blog-container">
                {% if not posts %}
                    <div class="no-posts">
                        <h2>Welcome to our blog!</h2>
                        <p>No posts published yet. Check back soon!</p>
                    </div>
                {% else %}
                    <div class="posts-list">
                        {% for post in posts %}
                            <article class="post-preview">
                                <h2 class="post-title"><a href="/post/{{ post.id }}">{{ post.title }}</a></h2>
                                <div class="post-meta">
                                    <span class="post-author">By {{ post.author.username }}</span>
                                    <span class="post-date">on {{ post.created_at.strftime('%B %d, %Y') }}</span>
                                </div>
                                
                                <div class="post-excerpt">
                                    {{ post.content[:300] }}
                                    {% if post.content|length > 300 %}
                                        ... <a href="/post/{{ post.id }}" class="read-more">Read more</a>
                                    {% endif %}
                                </div>
                            </article>
                        {% endfor %}
                    </div>
                {% endif %}
            </div>
        </main>

        <footer class="main-footer">
            <p>&copy; {{ current_year }} My Awesome Blog. All rights reserved.</p>
        </footer>
    </div>
</body>
</html>
"""

POST_DETAIL_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ post.title }} - My Awesome Blog</title>
    <style>
        :root {
            --primary: #4361ee;
            --primary-dark: #3a0ca3;
            --secondary: #3f37c9;
            --accent: #4895ef;
            --danger: #f72585;
            --success: #4cc9f0;
            --light: #f8f9fa;
            --dark: #212529;
            --gray: #6c757d;
            --white: #ffffff;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        
        body {
            background-color: #f5f7fb;
            color: var(--dark);
            line-height: 1.6;
        }
        
        .page-container {
            display: flex;
            flex-direction: column;
            min-height: 100vh;
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .main-header {
            background-color: var(--white);
            padding: 1rem 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .header-content {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .main-nav a {
            margin-left: 1.5rem;
            text-decoration: none;
            color: var(--primary);
            font-weight: 500;
        }
        
        .main-content {
            flex: 1;
            padding: 2rem;
        }
        
        .main-footer {
            background-color: var(--dark);
            color: var(--white);
            padding: 1.5rem;
            text-align: center;
        }
        
        .blog-container {
            max-width: 800px;
            margin: 0 auto;
        }
        
        .post-full, .post-preview {
            background-color: var(--white);
            border-radius: 8px;
            padding: 2rem;
            margin-bottom: 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .post-title {
            margin-bottom: 1rem;
            color: var(--dark);
        }
        
        .post-meta {
            color: var(--gray);
            margin-bottom: 1.5rem;
            font-size: 0.9rem;
        }
        
        .post-content {
            margin-bottom: 1.5rem;
            line-height: 1.7;
        }
        
        .comments-section {
            margin-top: 3rem;
            padding-top: 2rem;
            border-top: 1px solid #eee;
        }
        
        .comment {
            background-color: var(--light);
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }
        
        .comment-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 0.5rem;
        }
        
        .btn {
            display: inline-block;
            padding: 0.5rem 1rem;
            background-color: var(--primary);
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            text-decoration: none;
            font-size: 1rem;
        }
        
        .btn:hover {
            background-color: var(--primary-dark);
        }
        
        .form-group {
            margin-bottom: 1rem;
        }
        
        .form-group input,
        .form-group textarea {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 1rem;
        }
        
        .form-group textarea {
            min-height: 150px;
        }
        
        .error-message {
            background-color: #f8d7da;
            color: #721c24;
            padding: 1rem;
            border-radius: 4px;
            margin-bottom: 1.5rem;
        }
    </style>
</head>
<body>
    <div class="page-container">
        <header class="main-header">
            <div class="header-content">
                <h1><a href="/">My Awesome Blog</a></h1>
                <nav class="main-nav">
                    <a href="/">Home</a>
                    <a href="/admin">Admin</a>
                </nav>
            </div>
        </header>

        <main class="main-content">
            <div class="blog-container">
                <article class="post-full">
                    <h2 class="post-title">{{ post.title }}</h2>
                    <div class="post-meta">
                        <span class="post-author">By {{ post.author.username }}</span>
                        <span class="post-date">on {{ post.created_at.strftime('%B %d, %Y at %H:%M') }}</span>
                    </div>
                    
                    <div class="post-content">
                        {{ post.content }}
                    </div>
                    
                    <div class="post-actions">
                        <a href="/" class="btn back-btn">Back to All Posts</a>
                    </div>
                    
                    <section class="comments-section">
                        <h3>Comments</h3>
                        
                        {% for comment in comments %}
                            <div class="comment">
                                <div class="comment-header">
                                    <div class="comment-author">{{ comment.name }}</div>
                                    <div class="comment-date">{{ comment.created_at.strftime('%B %d, %Y at %H:%M') }}</div>
                                </div>
                                <div class="comment-content">
                                    {{ comment.content }}
                                </div>
                            </div>
                        {% else %}
                            <p>No comments yet. Be the first to comment!</p>
                        {% endfor %}
                        
                        <div class="add-comment">
                            <h4>Add a Comment</h4>
                            <form class="comment-form" onsubmit="return submitCommentForm(this)">
                                <div class="form-group">
                                    <input type="text" name="name" placeholder="Your Name" required>
                                </div>
                                <div class="form-group">
                                    <input type="email" name="email" placeholder="Your Email" required>
                                </div>
                                <div class="form-group">
                                    <textarea name="content" placeholder="Your Comment" required></textarea>
                                </div>
                                <input type="hidden" name="post_id" value="{{ post.id }}">
                                <button type="submit" class="btn submit-btn">Post Comment</button>
                            </form>
                        </div>
                    </section>
                </article>
            </div>
        </main>

        <footer class="main-footer">
            <p>&copy; {{ current_year }} My Awesome Blog. All rights reserved.</p>
        </footer>
    </div>

    <script>
        async function submitCommentForm(form) {
            const formData = new FormData(form);
            const data = {
                name: formData.get('name'),
                email: formData.get('email'),
                content: formData.get('content'),
                postId: formData.get('post_id')
            };

            try {
                const response = await fetch('/add_comment', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(data)
                });
                
                const result = await response.json();
                
                if (result.success) {
                    alert('Comment submitted successfully!');
                    form.reset();
                    location.reload();
                } else {
                    alert('Error: ' + (result.message || 'Failed to submit comment'));
                }
            } catch (error) {
                console.error('Error:', error);
                alert('There was an error submitting your comment. Please try again.');
            }
            
            return false;
        }
    </script>
</body>
</html>
"""

ADMIN_LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Login</title>
    <style>
        .login-container {
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            background-color: #f5f7fb;
        }
        
        .login-box {
            background-color: white;
            padding: 2rem;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            width: 100%;
            max-width: 400px;
        }
        
        .login-box h1 {
            text-align: center;
            margin-bottom: 1.5rem;
            color: #4361ee;
        }
        
        .form-group {
            margin-bottom: 1.5rem;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 600;
        }
        
        .form-group input {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 1rem;
        }
        
        .btn {
            width: 100%;
            padding: 0.75rem;
            background-color: #4361ee;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 1rem;
        }
        
        .btn:hover {
            background-color: #3a0ca3;
        }
        
        .error-message {
            background-color: #f8d7da;
            color: #721c24;
            padding: 1rem;
            border-radius: 4px;
            margin-bottom: 1.5rem;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-box">
            <h1>Admin Login</h1>
            {% if error %}
                <div class="error-message">{{ error }}</div>
            {% endif %}
            <form method="POST">
                <div class="form-group">
                    <label for="username">Username</label>
                    <input type="text" id="username" name="username" required>
                </div>
                <div class="form-group">
                    <label for="password">Password</label>
                    <input type="password" id="password" name="password" required>
                </div>
                <button type="submit" class="btn">Login</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

ADMIN_DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Dashboard</title>
    <style>
        :root {
            --primary: #4361ee;
            --primary-dark: #3a0ca3;
            --secondary: #3f37c9;
            --accent: #4895ef;
            --danger: #f72585;
            --success: #4cc9f0;
            --light: #f8f9fa;
            --dark: #212529;
            --gray: #6c757d;
            --white: #ffffff;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        
        body {
            background-color: #f5f7fb;
            color: var(--dark);
            line-height: 1.6;
        }
        
        .page-container {
            display: flex;
            flex-direction: column;
            min-height: 100vh;
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .main-header {
            background-color: var(--white);
            padding: 1rem 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .header-content {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .main-nav a {
            margin-left: 1.5rem;
            text-decoration: none;
            color: var(--primary);
            font-weight: 500;
        }
        
        .main-content {
            flex: 1;
            padding: 2rem;
        }
        
        .main-footer {
            background-color: var(--dark);
            color: var(--white);
            padding: 1.5rem;
            text-align: center;
        }
        
        .dashboard {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        
        .card {
            background-color: white;
            border-radius: 8px;
            padding: 1.5rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .card h2 {
            font-size: 1.5rem;
            margin-bottom: 1rem;
            color: var(--primary);
        }
        
        .stat-value {
            font-size: 2.5rem;
            font-weight: bold;
            color: var(--dark);
        }
        
        .recent-list {
            margin-top: 1rem;
        }
        
        .recent-item {
            padding: 0.75rem 0;
            border-bottom: 1px solid #eee;
        }
        
        .recent-item:last-child {
            border-bottom: none;
        }
        
        .btn {
            display: inline-block;
            padding: 0.5rem 1rem;
            background-color: var(--primary);
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            text-decoration: none;
            font-size: 1rem;
        }
        
        .btn:hover {
            background-color: var(--primary-dark);
        }
        
        .admin-nav {
            display: flex;
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
    </style>
</head>
<body>
    <div class="page-container">
        <header class="main-header">
            <div class="header-content">
                <h1><a href="/admin/dashboard">Admin Dashboard</a></h1>
                <nav class="main-nav">
                    <a href="/admin/dashboard">Dashboard</a>
                    <a href="/admin/posts">Manage Posts</a>
                    <a href="/admin/comments">Manage Comments</a>
                    <a href="/admin/new_post">New Post</a>
                    <a href="/admin/logout">Logout</a>
                </nav>
            </div>
        </header>

        <main class="main-content">
            <div class="admin-nav">
                <a href="/admin/dashboard" class="btn">Dashboard</a>
                <a href="/admin/posts" class="btn">Posts</a>
                <a href="/admin/comments" class="btn">Comments</a>
                <a href="/admin/new_post" class="btn">New Post</a>
            </div>
            
            {% if error %}
                <div class="error-message">{{ error }}</div>
            {% endif %}
            
            <div class="dashboard">
                <div class="card">
                    <h2>Total Posts</h2>
                    <div class="stat-value">{{ stats.total_posts }}</div>
                </div>
                
                <div class="card">
                    <h2>Pending Comments</h2>
                    <div class="stat-value">{{ stats.pending_comments }}</div>
                </div>
                
                <div class="card">
                    <h2>Online Users</h2>
                    <div class="stat-value">{{ stats.online_users }}</div>
                </div>
            </div>
            
            <div class="dashboard">
                <div class="card">
                    <h2>Recent Posts</h2>
                    <div class="recent-list">
                        {% for post in recent_posts %}
                            <div class="recent-item">
                                <a href="/post/{{ post.id }}">{{ post.title }}</a>
                                <div class="post-date">{{ post.created_at.strftime('%b %d, %Y') }}</div>
                            </div>
                        {% else %}
                            <p>No posts found</p>
                        {% endfor %}
                    </div>
                </div>
                
                <div class="card">
                    <h2>Recent Comments</h2>
                    <div class="recent-list">
                        {% for comment in recent_comments %}
                            <div class="recent-item">
                                <strong>{{ comment.name }}</strong> on 
                                <a href="/post/{{ comment.post_id }}">Post #{{ comment.post_id }}</a>
                                <p>{{ comment.content[:50] }}...</p>
                                <div class="comment-date">{{ comment.created_at.strftime('%b %d, %Y') }}</div>
                            </div>
                        {% else %}
                            <p>No comments found</p>
                        {% endfor %}
                    </div>
                </div>
            </div>
        </main>

        <footer class="main-footer">
            <p>&copy; {{ current_year }} My Awesome Blog. All rights reserved.</p>
        </footer>
    </div>
</body>
</html>
"""

ADMIN_POSTS_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Manage Posts</title>
    <style>
        /* Same styles as ADMIN_DASHBOARD_TEMPLATE */
    </style>
</head>
<body>
    <div class="page-container">
        <header class="main-header">
            <div class="header-content">
                <h1><a href="/admin/dashboard">Admin Dashboard</a></h1>
                <nav class="main-nav">
                    <a href="/admin/dashboard">Dashboard</a>
                    <a href="/admin/posts">Manage Posts</a>
                    <a href="/admin/comments">Manage Comments</a>
                    <a href="/admin/new_post">New Post</a>
                    <a href="/admin/logout">Logout</a>
                </nav>
            </div>
        </header>

        <main class="main-content">
            <div class="admin-nav">
                <a href="/admin/dashboard" class="btn">Dashboard</a>
                <a href="/admin/posts" class="btn">Posts</a>
                <a href="/admin/comments" class="btn">Comments</a>
                <a href="/admin/new_post" class="btn">New Post</a>
            </div>
            
            {% if error %}
                <div class="error-message">{{ error }}</div>
            {% endif %}
            
            <h2>Manage Posts</h2>
            <a href="/admin/new_post" class="btn">Create New Post</a>
            
            <div class="posts-list" style="margin-top: 2rem;">
                {% for post in posts %}
                    <div class="card" style="margin-bottom: 1rem;">
                        <h3>{{ post.title }}</h3>
                        <p>Status: {{ 'Published' if post.is_published else 'Draft' }}</p>
                        <p>Created: {{ post.created_at.strftime('%B %d, %Y') }}</p>
                        
                        <div style="margin-top: 1rem; display: flex; gap: 0.5rem;">
                            <form method="POST" style="display: inline;">
                                <input type="hidden" name="post_id" value="{{ post.id }}">
                                <input type="hidden" name="action" value="toggle">
                                <button type="submit" class="btn">
                                    {{ 'Unpublish' if post.is_published else 'Publish' }}
                                </button>
                            </form>
                            
                            <form method="POST" style="display: inline;">
                                <input type="hidden" name="post_id" value="{{ post.id }}">
                                <input type="hidden" name="action" value="delete">
                                <button type="submit" class="btn" style="background-color: var(--danger);">
                                    Delete
                                </button>
                            </form>
                            
                            <a href="/post/{{ post.id }}" class="btn" target="_blank">View</a>
                        </div>
                    </div>
                {% else %}
                    <p>No posts found</p>
                {% endfor %}
            </div>
        </main>

        <footer class="main-footer">
            <p>&copy; {{ current_year }} My Awesome Blog. All rights reserved.</p>
        </footer>
    </div>
</body>
</html>
"""

ADMIN_COMMENTS_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Manage Comments</title>
    <style>
        /* Same styles as ADMIN_DASHBOARD_TEMPLATE */
    </style>
</head>
<body>
    <div class="page-container">
        <header class="main-header">
            <div class="header-content">
                <h1><a href="/admin/dashboard">Admin Dashboard</a></h1>
                <nav class="main-nav">
                    <a href="/admin/dashboard">Dashboard</a>
                    <a href="/admin/posts">Manage Posts</a>
                    <a href="/admin/comments">Manage Comments</a>
                    <a href="/admin/new_post">New Post</a>
                    <a href="/admin/logout">Logout</a>
                </nav>
            </div>
        </header>

        <main class="main-content">
            <div class="admin-nav">
                <a href="/admin/dashboard" class="btn">Dashboard</a>
                <a href="/admin/posts" class="btn">Posts</a>
                <a href="/admin/comments" class="btn">Comments</a>
                <a href="/admin/new_post" class="btn">New Post</a>
            </div>
            
            {% if error %}
                <div class="error-message">{{ error }}</div>
            {% endif %}
            
            <h2>Manage Comments</h2>
            
            <div class="comments-list" style="margin-top: 2rem;">
                {% for comment in comments %}
                    <div class="card" style="margin-bottom: 1rem;">
                        <h3>{{ comment.name }} &lt;{{ comment.email }}&gt;</h3>
                        <p>Status: {{ 'Approved' if comment.is_approved else 'Pending' }}</p>
                        <p>Post: <a href="/post/{{ comment.post_id }}">#{{ comment.post_id }}</a></p>
                        <p>{{ comment.content }}</p>
                        <p>Created: {{ comment.created_at.strftime('%B %d, %Y at %H:%M') }}</p>
                        
                        <div style="margin-top: 1rem; display: flex; gap: 0.5rem;">
                            <form method="POST" style="display: inline;">
                                <input type="hidden" name="comment_id" value="{{ comment.id }}">
                                <input type="hidden" name="action" value="toggle">
                                <button type="submit" class="btn">
                                    {{ 'Unapprove' if comment.is_approved else 'Approve' }}
                                </button>
                            </form>
                            
                            <form method="POST" style="display: inline;">
                                <input type="hidden" name="comment_id" value="{{ comment.id }}">
                                <input type="hidden" name="action" value="delete">
                                <button type="submit" class="btn" style="background-color: var(--danger);">
                                    Delete
                                </button>
                            </form>
                        </div>
                    </div>
                {% else %}
                    <p>No comments found</p>
                {% endfor %}
            </div>
        </main>

        <footer class="main-footer">
            <p>&copy; {{ current_year }} My Awesome Blog. All rights reserved.</p>
        </footer>
    </div>
</body>
</html>
"""

ADMIN_NEW_POST_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>New Post</title>
    <style>
        /* Same styles as ADMIN_DASHBOARD_TEMPLATE */
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 600;
        }
        
        .form-group input,
        .form-group textarea,
        .form-group select {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 1rem;
        }
        
        .form-group textarea {
            min-height: 300px;
        }
    </style>
</head>
<body>
    <div class="page-container">
        <header class="main-header">
            <div class="header-content">
                <h1><a href="/admin/dashboard">Admin Dashboard</a></h1>
                <nav class="main-nav">
                    <a href="/admin/dashboard">Dashboard</a>
                    <a href="/admin/posts">Manage Posts</a>
                    <a href="/admin/comments">Manage Comments</a>
                    <a href="/admin/new_post">New Post</a>
                    <a href="/admin/logout">Logout</a>
                </nav>
            </div>
        </header>

        <main class="main-content">
            <div class="admin-nav">
                <a href="/admin/dashboard" class="btn">Dashboard</a>
                <a href="/admin/posts" class="btn">Posts</a>
                <a href="/admin/comments" class="btn">Comments</a>
                <a href="/admin/new_post" class="btn">New Post</a>
            </div>
            
            {% if error %}
                <div class="error-message">{{ error }}</div>
            {% endif %}
            
            <h2>Create New Post</h2>
            
            <form method="POST" class="card" style="padding: 2rem;">
                <div class="form-group">
                    <label for="title">Title</label>
                    <input type="text" id="title" name="title" required>
                </div>
                
                <div class="form-group">
                    <label for="content">Content</label>
                    <textarea id="content" name="content" required></textarea>
                </div>
                
                <div class="form-group">
                    <label for="status">Status</label>
                    <select id="status" name="status">
                        <option value="published">Published</option>
                        <option value="draft">Draft</option>
                    </select>
                </div>
                
                <button type="submit" class="btn">Create Post</button>
            </form>
        </main>

        <footer class="main-footer">
            <p>&copy; {{ current_year }} My Awesome Blog. All rights reserved.</p>
        </footer>
    </div>
</body>
</html>
"""

# Initialize the application
if __name__ == '__main__':
    init_admin()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
else:
    init_admin()
