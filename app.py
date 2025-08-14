from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
from sqlalchemy import desc

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or 'dev-secret-key-123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blog.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
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

# Initialize Database
def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', online=True)
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()

# Routes
@app.route('/')
def home():
    posts = Post.query.filter_by(is_published=True).order_by(Post.created_at.desc()).all()
    return render_template('blog.html', posts=posts)

@app.route('/post/<int:post_id>')
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    comments = Comment.query.filter_by(post_id=post_id, parent_id=None, is_approved=True).all()
    return render_template('blog.html', post=post, comments=comments)

@app.route('/add_comment', methods=['POST'])
def add_comment():
    data = request.get_json()
    if not all(key in data for key in ['name', 'email', 'content', 'postId']):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400
    
    new_comment = Comment(
        post_id=data['postId'],
        parent_id=data.get('parentId'),
        name=data['name'],
        email=data['email'],
        content=data['content']
    )
    
    db.session.add(new_comment)
    db.session.commit()
    return jsonify({'success': True, 'comment_id': new_comment.id})

@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            user.online = True
            user.last_seen = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('admin_dashboard'))
        return render_template('admin.html', error='Invalid credentials')
    return render_template('admin.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('admin_login'))
    
    stats = {
        'total_posts': Post.query.count(),
        'pending_comments': Comment.query.filter_by(is_approved=False).count(),
        'online_users': User.query.filter_by(online=True).count()
    }
    
    recent_posts = Post.query.order_by(Post.created_at.desc()).limit(5).all()
    recent_comments = Comment.query.order_by(Comment.created_at.desc()).limit(5).all()
    
    return render_template('admin.html', 
                         stats=stats,
                         recent_posts=recent_posts,
                         recent_comments=recent_comments,
                         section='dashboard')

@app.route('/admin/posts', methods=['GET', 'POST'])
def manage_posts():
    if 'user_id' not in session:
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        post_id = request.form.get('post_id')
        action = request.form.get('action')
        
        if action == 'delete':
            Post.query.filter_by(id=post_id).delete()
        elif action == 'toggle':
            post = Post.query.get(post_id)
            post.is_published = not post.is_published
        
        db.session.commit()
    
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template('admin.html', posts=posts, section='posts')

@app.route('/admin/comments', methods=['GET', 'POST'])
def manage_comments():
    if 'user_id' not in session:
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        comment_id = request.form.get('comment_id')
        action = request.form.get('action')
        
        if action == 'delete':
            Comment.query.filter_by(id=comment_id).delete()
        elif action == 'toggle':
            comment = Comment.query.get(comment_id)
            comment.is_approved = not comment.is_approved
        
        db.session.commit()
    
    comments = Comment.query.order_by(Comment.created_at.desc()).all()
    return render_template('admin.html', comments=comments, section='comments')

@app.route('/admin/new_post', methods=['GET', 'POST'])
def new_post():
    if 'user_id' not in session:
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        status = request.form.get('status', 'published')
        
        new_post = Post(
            title=title,
            content=content,
            author_id=session['user_id'],
            is_published=(status == 'published')
        )
        
        db.session.add(new_post)
        db.session.commit()
        return redirect(url_for('manage_posts'))
    
    return render_template('admin.html', section='new_post')

@app.route('/admin/logout')
def admin_logout():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.online = False
            db.session.commit()
    session.pop('user_id', None)
    return redirect(url_for('home'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
