import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from sqlalchemy import desc
from models import db, User, Post, Comment  # Import from models.py

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
db.init_app(app)

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
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()

# Routes
@app.route('/')
def home():
    try:
        posts = Post.query.filter_by(is_published=True).order_by(Post.created_at.desc()).all()
        return render_template('blog.html', posts=posts)
    except Exception as e:
        return render_template('error.html', message="Service is starting. Please refresh in a moment."), 503

@app.route('/post/<int:post_id>')
def post_detail(post_id):
    try:
        post = Post.query.get_or_404(post_id)
        comments = Comment.query.filter_by(post_id=post_id, parent_id=None, is_approved=True).all()
        return render_template('blog.html', post=post, comments=comments)
    except Exception as e:
        return render_template('error.html', message="Post not found"), 404

@app.route('/add_comment', methods=['POST'])
def add_comment():
    try:
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
            return render_template('admin.html', error='Invalid credentials')
        except Exception as e:
            return render_template('admin.html', error='Internal server error')
    return render_template('admin.html')

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
        
        return render_template('admin.html', 
                            stats=stats,
                            recent_posts=recent_posts,
                            recent_comments=recent_comments,
                            section='dashboard')
    except Exception as e:
        return render_template('admin.html', error='Database error'), 500

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
                post.is_published = not post.is_published
            
            db.session.commit()
        except Exception as e:
            db.session.rollback()
    
    try:
        posts = Post.query.order_by(Post.created_at.desc()).all()
        return render_template('admin.html', posts=posts, section='posts')
    except Exception as e:
        return render_template('admin.html', error='Database error'), 500

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
                comment.is_approved = not comment.is_approved
            
            db.session.commit()
        except Exception as e:
            db.session.rollback()
    
    try:
        comments = Comment.query.order_by(Comment.created_at.desc()).all()
        return render_template('admin.html', comments=comments, section='comments')
    except Exception as e:
        return render_template('admin.html', error='Database error'), 500

@app.route('/admin/new_post', methods=['GET', 'POST'])
def new_post():
    if 'user_id' not in session:
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        try:
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
        except Exception as e:
            db.session.rollback()
            return render_template('admin.html', error='Failed to create post', section='new_post')
    
    return render_template('admin.html', section='new_post')

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

if __name__ == '__main__':
    init_admin()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
