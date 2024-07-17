from flask import Flask, render_template, url_for, flash, redirect, \
    request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_behind_proxy import FlaskBehindProxy
from flask_login import UserMixin, LoginManager, login_user, \
    login_required, logout_user, current_user
import openai
from openai import OpenAI
import os
import git
from flashcards import run_flashcards
from quiz import run_quiz


# The SQLAlchemy object is created and used to interact with the database.
db = SQLAlchemy()

# SUBJECT_SUBTOPIC_DICT is a dictionary that contains the subjects as keys
# and the subtopics as values.
SUBJECT_SUBTOPIC_DICT = {
    "Physics": [
        "Mechanics",
        "Electromagnetism",
        "Thermodynamics",
        "Optics",
        "Modern Physics",
        "Astrophysics"
    ],
    "Chemistry": [
        "Organic Chemistry",
        "Inorganic Chemistry",
        "Physical Chemistry",
        "Analytical Chemistry",
        "Biochemistry",
        "Environmental Chemistry"
    ],
    "Biology": [
        "Cell Biology",
        "Genetics",
        "Ecology",
        "Evolution",
        "Human Anatomy and Physiology",
        "Microbiology"
    ],
    "Computer-Science": [
        "Data Structures and Sorting Algorithms",
        "Software Engineering",
        "Artificial Intelligence",
        "Databases",
        "Computer Networks",
        "Cybersecurity"
    ],
    "History": [
        "Ancient Civilizations",
        "Medieval History",
        "Modern History",
        "American History",
        "World History",
        "Cultural History"
    ],
    "Economics": [
        "Microeconomics",
        "Macroeconomics",
        "International Economics",
        "Development Economics",
        "Behavioral Economics",
        "Environmental Economics"
    ]
}


# Used when Signing in and Signing up
class User(UserMixin, db.Model):
    # primary keys are required by SQLAlchemy
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))  # Stores only hashed passwords
    name = db.Column(db.String(1000))

    # Each user will have multiple quiz results they will want to access
    quiz_results = db.relationship('QuizResult', backref='user')

    # String representation of a user for debugging purposes
    def __repr__(self):
        return f'<User: {self.name} :: {self.email}>'


# Used for storing prior quiz results
class QuizResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    time = db.Column(db.DateTime)  # The time the quiz was completed
    subject = db.Column(db.String(100))
    subtopic = db.Column(db.String(100))
    num_correct = db.Column(db.Integer)

    # Represents the user that took this quiz; links back to User table
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    # String representation of a quiz result for debugging purposes
    def __repr__(self):
        return f"<{self.user.name}'s Quiz Result :: " \
               f"{self.subtopic} ({self.subject}) : {self.num_correct} / 5>"


# The OpenAI API key is stored in an environment variable and used to
# authenticate the OpenAI API, stored in the CLIENT constant.
MY_API_KEY = os.environ.get('OPENAI_KEY')
openai.api_key = MY_API_KEY
CLIENT = OpenAI(api_key=MY_API_KEY,)

# Basic App Configuration
app = Flask(__name__)
app.config['SESSION_TYPE'] = 'filesystem'
proxied = FlaskBehindProxy(app)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tutor.db'

# Initialize the database if it doesn't already exist
db.init_app(app)
with app.app_context():
    db.create_all()

# Initialize the Login Manager
login_manager = LoginManager()
login_manager.login_view = "signin"
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    # since the user_id is just the primary key of our user table,
    # use it in the query for the user
    return User.query.get(int(user_id))


@app.route("/")
@app.route("/home")
def home():
    return render_template('home.html', title='Home')


# This route prompts the user for a subject and subtopic before actually
# displaying the flashcards.
@app.route("/flashcards")
@login_required
def flashcards():
    return render_template('topics.html', subjects=SUBJECT_SUBTOPIC_DICT,
                           subject_dictionary=SUBJECT_SUBTOPIC_DICT)


# This route is used to display the flashcards page with the subject and
# subtopic selected by the user. The subject and subtopic are passed as
# parameters in the URL from the previous form submission.
@app.route("/flashcards", methods=['POST'])
@login_required
def flashcards_post():
    subject = request.form.get('subject_selection')
    subtopic = request.form.get('subtopic_selection')

    return render_template('flashcards.html', title='Flashcards',
                           subject=subject, subtopic=subtopic)


# This route is used to generate the flashcards based on the subject and
# subtopic selected by the user. The subject and subtopic are passed as
# parameters to the URL from a AJAX request from the JS script
# embedded in /templates/flashcards.html.
@app.route("/get-cards", methods=['POST'])
def get_cards():
    data = request.json
    subject = data.get("subject")
    subtopic = data.get("subtopic")
    flashcards = run_flashcards(CLIENT, subject, subtopic)
    return jsonify(flashcards)


# This route prompts the user for a subject and subtopic before actually
# displaying the quiz.
@app.route("/quiz")
@login_required
def quiz():
    return render_template('topics.html', subjects=SUBJECT_SUBTOPIC_DICT,
                           subject_dictionary=SUBJECT_SUBTOPIC_DICT)


# This route displays the quiz based on the subject and subtopic selected
# by the user on the previous form.
@app.route("/quiz", methods=['POST'])
@login_required
def quiz_post():
    subject = request.form.get('subject_selection')
    subtopic = request.form.get('subtopic_selection')
    return render_template('quiz.html', title='Quiz', subject=subject,
                           subtopic=subtopic)


# Creates quiz questions based on the subject and subtopic provided in
# the url. The questions are returned in a JSON format to be used by
# the JS Script in templates/quiz.html.
@app.route("/generate_quiz", methods=['POST'])
def generate_quiz():
    data = request.json
    subject = data.get("subject")
    subtopic = data.get("subtopic")
    quiz_data = run_quiz(CLIENT, subject, subtopic)
    return jsonify(quiz_data)


@app.route("/signin")
def signin():
    return render_template('signin.html', title='Sign In')


@app.route('/signin', methods=['POST'])
def signin_post():
    email = request.form.get('email')
    password = request.form.get('password')
    remember = True if request.form.get('remember') else False

    user = User.query.filter_by(email=email).first()

    # check if the user actually exists
    # take the user-supplied password, hash it, and compare it to the
    # hashed password in the database
    if not user or not check_password_hash(user.password, password):
        # if the user doesn't exist or password is wrong, reload the page
        flash('Please check your login details and try again.')
        return redirect(url_for('signin'))

    # if the above check passes, we know the user has the right credentials
    login_user(user, remember=remember)
    return redirect(url_for('home'))


@app.route("/signup")
def signup():
    return render_template('signin.html', title='Sign Up')


@app.route('/signup', methods=['POST'])
def signup_post():
    email = request.form.get('email')
    name = request.form.get('name')
    password = request.form.get('password')

    # if this returns a user, then the email already exists in database
    user = User.query.filter_by(email=email).first()

    # if a user is found, redirect back to signup page so user can try again
    if user:
        flash('Email address already exists')
        return redirect(url_for('signup'))

    # create a new user with the form data.
    # Hash the password so the plaintext version isn't saved.
    new_user = User(
        email=email,
        name=name,
        password=generate_password_hash(password, method='pbkdf2:sha256')
    )

    # add the new user to the database
    db.session.add(new_user)
    db.session.commit()

    return redirect(url_for('signin'))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


# Dummy way to add quiz results; change later
@app.route('/add_result/<subject>/<subtopic>/<int:score>')
@login_required
def add_result(subject, subtopic, score):
    result = QuizResult(
        time=None,
        subject=subject,
        subtopic=subtopic,
        num_correct=score,
        user=current_user
    )
    db.session.add(result)
    db.session.commit()

    return redirect(url_for('quiz_results'))


# This is just used for testing purposes to make sure quiz results are
# stored correctly in the database for each user
@app.route('/quiz_results')
@login_required
def quiz_results():
    results = list(current_user.quiz_results)
    results.reverse()
    return render_template('quiz_results.html', title='Quiz Results',
                           results=results)


# This route is used by pythonanywhere to update the server automatically
#  when a push is made to the GitHub repository.
@app.route("/update_server", methods=['POST'])
def webhook():
    if request.method == 'POST':
        repo = git.Repo('/home/LearnMateAI/LearnMate')
        origin = repo.remotes.origin
        origin.pull()
        return 'Updated PythonAnywhere successfully', 200
    else:
        return 'Wrong event type', 400


if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=8080)
