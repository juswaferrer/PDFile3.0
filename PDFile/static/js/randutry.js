document.getElementById('user_input').addEventListener('submit', function(event) {
    event.preventDefault();

    var formData = new FormData();
    formData.append('pdf_file', document.getElementById('pdf_file').files[0]);
    formData.append('user_query', document.getElementById('user_query').value);

    // Get user question
    var userQuestion = document.getElementById('user_query').value;

    fetch('/chat', {
        method: 'POST',
        body: formData
    })
    .then(response => response.text())
    .then(data => {
        // Show loading animation with user question
        var responseContainer = document.getElementById('response');
        responseContainer.innerHTML += `
            <div class="message-container">
                <div class="user-message">${userQuestion}</div>
                <div class="bot-message bot-loading">...</div>
            </div>`;

        // Update response after a short delay to simulate bot response time
        setTimeout(function() {
            var botLoading = document.querySelector('.bot-loading');
            botLoading.innerText = data;
            botLoading.classList.remove('bot-loading');

            // Clear the input box
            document.getElementById('user_query').value = '';
        }, 1000);
    })
    .catch(error => console.error('Error:', error));
});
