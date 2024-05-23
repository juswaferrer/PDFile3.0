from flask import Flask, request, render_template, redirect, url_for, session, current_app, jsonify
import io
from PyPDF2 import PdfReader
from transformers import AutoTokenizer, AutoModelForQuestionAnswering, pipeline
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
import os
import re
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Load QA model and tokenizer
model_name = "distilbert/distilbert-base-cased-distilled-squad"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForQuestionAnswering.from_pretrained(model_name)
qa_pipeline = pipeline("question-answering", model=model, tokenizer=tokenizer)

with app.app_context():
    root_path = current_app.root_path
    file_path = os.path.join(root_path, "firebase.json")
    cred = credentials.Certificate(file_path)
    firebase_admin.initialize_app(cred)
    db = firestore.client()

pdf_conversations = {}
# Function to extract text and title from PDF
def extract_text_and_title_from_pdf(pdf_content):
    try:
        pdf_file = io.BytesIO(pdf_content)
        pdf_reader = PdfReader(pdf_file)
        text = ""
        title = pdf_reader.metadata.title if pdf_reader.metadata.title else None
        for page in pdf_reader.pages:
            text += page.extract_text()
        if not title:
            title = text[:30] + "..." if len(text) > 30 else text
        return title, text
    except Exception as e:
        raise Exception("Error extracting text from PDF.")

def find_supporting_evidence(answer, context):
    pattern = rf"\b{re.escape(answer)}\b"
    sentences = re.findall(r"[^\.!\?]+[\.!\?]", context, flags=re.DOTALL)
    for sentence in sentences:
        if re.search(pattern, sentence, flags=re.IGNORECASE):
            cleaned_sentence = re.sub(r'\d+', '', sentence)
            cleaned_sentence = re.sub(r'[^\w\s]', '', cleaned_sentence)
            cleaned_sentence = " ".join(cleaned_sentence.split())
            return cleaned_sentence.strip()  # Return only the relevant part of the sentence
    return ""  # Return an empty string if no evidence found

def get_page_numbers(evidence_sentence, context, window_size=50):
    pattern = r"(?:Page|p\.)\s*(\d+)"
    matches = re.findall(pattern, context, flags=re.IGNORECASE)
    page_numbers = []

    if not matches:
        return "not available"

    sentence_start = context.find(evidence_sentence)

    for match in matches:
        page_num = int(match)
        if sentence_start - window_size < context.find(match) < sentence_start + window_size:
            page_numbers.append(str(page_num))

    if page_numbers:
        return ", ".join(page_numbers)
    else:
        return "not available"

def re_search_pdf(question, context):
    try:
        paragraphs = context.split("\n\n")
        best_answer = None
        best_supporting_evidence = None

        for paragraph in paragraphs:
            answer = qa_pipeline(question=question, context=paragraph)

            if not best_answer or answer["score"] > best_answer["score"]:
                best_answer = answer
                best_supporting_evidence = find_supporting_evidence(answer["answer"], paragraph)

        if best_answer:
            formatted_answer = best_answer["answer"]
            page_numbers = get_page_numbers(best_supporting_evidence, context)
            return {
                "formatted_answer": formatted_answer,
                "supporting_evidence": best_supporting_evidence,
                "page_numbers": page_numbers
            }
        else:
            return None

    except Exception as e:
        raise Exception(f"Error re-searching the PDF: {e}")

def answer_question(question, context):
    try:
        answer_info = re_search_pdf(question, context)

        if answer_info:
            formatted_answer = answer_info["formatted_answer"]
            supporting_evidence = answer_info["supporting_evidence"]
            page_numbers = answer_info["page_numbers"]
            full_answer = f"The answer to your question '{question}' is: {formatted_answer}. "
            full_answer += f"According to the PDF, {supporting_evidence}. "
            full_answer += f"This information is found on page(s): {page_numbers}."
        else:
            answer = qa_pipeline(question=question, context=context)
            answer_text = answer["answer"]
            evidence = find_supporting_evidence(answer_text, context)
            full_answer = f"The answer to your question '{question}' is: {answer_text}. "
            if evidence:
                full_answer += f"According to the PDF, {evidence}. "
            else:
                full_answer += "No additional context found in the PDF."

        return full_answer

    except Exception as e:
        raise Exception("Error answering the question.")

@app.route('/')
def index():
    return render_template('frontpage.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        try:
            users_ref = db.collection('PDFile')
            query = users_ref.where('username', '==', username).limit(1).get()  # Use get() instead of stream()
            user_doc = None
            for doc in query:
                user_doc = doc.to_dict()
                break

            if user_doc and user_doc['password'] == password:
                session['username'] = username
                return redirect(url_for('pdfile'))
            else:
                error = 'Invalid Credentials. Please try again.'
        except Exception as e:
            error = str(e)
    return render_template('login.html', error=error)

password_pattern = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^a-zA-Z\d\s]).+$")

def generate_otp():
    return str(random.randint(100000, 999999))

# Send OTP to email
def send_otp(email, otp):
    sender_email = "name0956@gmail.com"
    sender_password = "xehy bghc slhn ssam"
    subject = "Your OTP Code"

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = email
    msg['Subject'] = subject
    body = f"Your OTP code is {otp}"
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        text = msg.as_string()
        server.sendmail(sender_email, email, text)
        server.quit()
    except Exception as e:
        raise Exception(f"Failed to send OTP: {str(e)}")

@app.route('/send_otp', methods=['POST'])
def send_otp_route():
    try:
        email = request.json.get('email')  # Get the 'email' value from JSON data
        app.logger.info(f'Received email: {email}')  # Log the received email
        otp = generate_otp()
        send_otp(email, otp)
        session['otp'] = otp
        return jsonify({'status': 'success'})  # Return success response
    except Exception as e:
        app.logger.error(f'Error: {str(e)}')  # Log any errors that occur
        return jsonify({'status': 'error', 'message': str(e)}), 500  # Return error response

# Verify OTP
@app.route('/verify_otp', methods=['POST'])
def verify_otp_route():
    user_otp = request.form['otp']
    if 'otp' in session and session['otp'] == user_otp:
        session.pop('otp', None)
        return "OTP verified successfully"
    else:
        return "Invalid OTP", 400

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        otp = request.form['otp']

        if 'otp' not in session or session['otp'] != otp:
            error = 'Invalid OTP. Please verify your email.'
            return render_template('signup.html', error=error)

        if not password_pattern.match(password):
            error = 'Password must contain at least one lowercase letter, one uppercase letter, one digit, and one special character.'
        else:
            try:
                users_ref = db.collection('PDFile')
                username_query = users_ref.where('username', '==', username).get()
                email_query = users_ref.where('email', '==', email).get()

                if username_query:
                    error = 'Username already exists. Please choose a different username.'
                elif email_query:
                    error = 'Email already exists. Please use a different email.'
                else:
                    users_ref.add({
                        'username': username,
                        'email': email,
                        'password': password
                    })
                    session.pop('otp', None)
                    session['username'] = username
                    return redirect(url_for('pdfile'))
            except Exception as e:
                error = str(e)

    return render_template('signup.html', error=error)

@app.route('/forgotpass', methods=['GET', 'POST'])
def forgot_password():
    error = None
    if request.method == 'POST':
        email = request.form.get('email')
        user_code = request.form.get('code')
        new_password = request.form.get('password')

        if email and not user_code and not new_password:
            # Stage 1: Send OTP
            otp = generate_otp()
            try:
                send_otp(email, otp)
                session['otp'] = otp
                session['otp_email'] = email  # Store email in session for later verification
                return render_template('forgotpass.html', email=email, show_fields=True)
            except Exception as e:
                error = str(e)
        
        elif email and user_code and new_password:
            # Stage 2: Verify OTP and reset password
            if 'otp' in session and session.get('otp') == user_code and session.get('otp_email') == email:
                try:
                    # Update user's password in the database
                    users_ref = db.collection('PDFile')
                    user_query = users_ref.where('email', '==', email).limit(1).get()
                    if user_query:
                        for doc in user_query:
                            user_ref = doc.reference
                            user_ref.update({'password': new_password})
                        session.pop('otp', None)
                        session.pop('otp_email', None)
                        return redirect(url_for('login'))
                    else:
                        error = 'User not found.'
                except Exception as e:
                    error = str(e)
            else:
                error = 'Invalid OTP or email mismatch. Please try again.'
        else:
            error = 'All fields are required.'
    
    return render_template('forgotpass.html', error=error)

@app.route('/pdfile')
def pdfile():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('PDFile.html')

@app.route('/chat', methods=['POST'])
def chat():
    if 'username' not in session:
        return redirect(url_for('login'))

    pdf_file = request.files['pdf_file']
    pdf_content = pdf_file.read()
    
    if not pdf_content:
        return "Please upload a PDF file."
    
    user_question = request.form['user_query']

    if not user_question:
        return "Please provide a question."

    try:
        title, pdf_text = extract_text_and_title_from_pdf(pdf_content)
        answer = answer_question(user_question, pdf_text)

        # Store conversation in pdf_conversations
        if title not in pdf_conversations:
            pdf_conversations[title] = []
        pdf_conversations[title].append({'question': user_question, 'answer': answer})

        return jsonify({'title': title, 'answer': answer})
    except Exception as e:
        return jsonify({'error': f"Error: {e}"})

@app.route('/conversations', methods=['GET'])
def get_conversations():
    return jsonify(pdf_conversations)
    

if __name__ == '__main__':
    app.run(debug=True)