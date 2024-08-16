import json
import re
from PIL import Image
import base64

import streamlit as st
import streamlit.components.v1 as components

from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage
from openai import OpenAI
from openai import AzureOpenAI
import google.generativeai as genai
import ollama

from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.llms import ollama as langchain_ollama
from langchain.vectorstores import Chroma
from langchain.chains import RetrievalQA
from langchain.document_loaders import TextLoader, CSVLoader, PyPDFLoader
from langchain_text_splitters import CharacterTextSplitter

# ------------------ Helper Functions ------------------ #

# Function to create embeddings
def create_embeddings(uploaded_files, chunk_size=4000, chunk_overlap=400):
    documents = []

    if uploaded_files is not None and type(uploaded_files) is list and len(uploaded_files) > 0:
        # process the uploaded files
        for file in uploaded_files:
            file_name = file.name
            file_content = file.read()

            if file_name.endswith(".txt"):
                loader = TextLoader(file_content)
            elif file_name.endswith(".csv"):
                loader = CSVLoader(file_content)
            elif file_name.endswith(".pdf"):
                loader = PyPDFLoader(file_content)
            else:
                # Handle unsupported file types gracefully
                st.error(f"Unsupported file type: {file_name}")
                continue

            documents.append(loader.load())

        # Split documents into chunks
        text_splitter = CharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        docs = text_splitter.split_documents(documents)

        # Create embeddings database (Chroma)
        embeddings = OpenAIEmbeddings()
        db = Chroma.from_documents(docs, embeddings)

        return db
    else:
        return None

# Function to get user document upload for RAG
def get_rag_document_input(max_files=3, max_size=20):
    uploaded_files = st.file_uploader("Choose document for RAG...", type=["pdf", "csv", "txt"], accept_multiple_files=True)
    removed_files = []

    if uploaded_files is not None:
        # check the file sizes
        for file in uploaded_files:
            if file.size > max_size * 1024 * 1024:
                # remove the file from the list
                removed_files.append(file)
                uploaded_files.remove(file)
        
        # print the warning message if any file is removed
        if len(removed_files) > 0:
            st.warning(f"File(s) {", ".join([file.name for file in removed_files])}larger than {max_size} MB are removed. Please upload file(s) smaller than {max_size} MB.")

        # check the number of files uploaded
        if len(uploaded_files) > max_files:
            st.warning(f"Please upload only {max_files} file(s). Only the first {max_files} file(s) will be processed.")
            uploaded_files = uploaded_files[:max_files]

    return uploaded_files


# Function to encode the image
def encode_image(image_file):
    b64_image = base64.b64encode(image_file.getvalue()).decode("utf-8")
    return b64_image
    # if filetype == "png":
    #     return f"data:image/png;base64,{b64_image}"
    # else:
    #     return f"data:image/jpeg;base64,{b64_image}"


# Function to get user image upload
def get_image_input(max_files=1):
    uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "png"], accept_multiple_files=False)

    if uploaded_file is not None:
        # # check the number of files uploaded
        # if len(uploaded_file) > max_files:
        #     st.warning(f"Please upload only {max_files} file(s). Only the first {max_files} file(s) will be processed.")
        #     uploaded_file = uploaded_file[:max_files]
        image = Image.open(uploaded_file)
        st.image(image, caption='Uploaded Image.', width=200)
        return uploaded_file, uploaded_file.name, uploaded_file.type
        # image_base64 = encode_image(uploaded_file.getvalue())
        # return image_base64
    else:
        return None, None, None
    
# Function to create a prompt for generating a threat model
def create_image_description_prompt():
    prompt = f"""Act as a cyber security expert with more than 20 years experience of in system and application security architecture. Your task is to describe the image in detail.
With the provided image, identify components, the role of the component, and the connections.
Include details such as technology, network protocols, authentication, logging, software version, development lifeycle, operating model, patch management, data protection if it can be identified from the diagram."""
    return prompt

# Function to get image description from the GPT response.
def get_image_description(api_key, model_name, prompt, image_type, image_base64, max_tokens=4000):
    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image_type};base64,{image_base64}"
                        }
                    }
                ],
            }
        ],
        max_tokens=max_tokens,
    )

    # Convert the JSON string in the 'content' field to a Python dictionary
    response_content = response.choices[0].message.content

    return response_content

# Function to get image description from the Azure OpenAI response.
def get_image_description_azure(api_endpoint, api_key, api_version, deployment_name, prompt, image_type, image_base64, max_tokens=4000):
    client = AzureOpenAI(
        azure_endpoint = api_endpoint,
        api_key = api_key,
        api_version = api_version,
    )

    response = client.chat.completions.create(
        model=deployment_name,
        messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image_type};base64,{image_base64}"
                            }
                        }
                    ],
                }
        ],
        max_tokens=max_tokens,
    )

    # Convert the JSON string in the 'content' field to a Python dictionary
    response_content = json.loads(response.choices[0].message.content)

    return response_content

# Function to get image description from Mistral.
def get_image_description_mistral(api_key, model_name, prompt, image_type, image_base64):

    return "Currently not supported."

# Function to get image description from Google Gemini.
def get_image_description_google_gemini(api_key, model_name, prompt, image):
    genai.configure(api_key=api_key)
    gemini_model = genai.GenerativeModel(model_name=model_name)

    response = gemini_model.generate_content(
        [prompt, Image.open(image)],
        stream=True
        # [model_behaviour, image_info[0], prompt],
        # model="gemini-pro-vision",
    )
    response.resolve()

    return response.candidates[0].content.parts[0].text
    # return response.text

# Function to get image description from local model
def get_image_description_local(model_name, prompt, image):
    response = ollama.chat(
        model=model_name,
        messages=[
            {
                'role': 'user',
                'content': prompt,
                'images': [image.getvalue()]
            }
        ]
    )

    # Convert the JSON string in the 'content' field to a Python dictionary
    response_content = response['message']['content']

    return response_content

# Function to get user input for the application description and key details
def get_input(app_input_session_state_key="app_input"):

    input_text = st.text_area(
        label="Describe the application to be modelled",
        placeholder="Enter your application details...",
        value=st.session_state[app_input_session_state_key],
        height=150,
        # key=app_input_session_state_key,
        help="Please provide a detailed description of the application, including the purpose of the application, the technologies used, and any other relevant information.",
    )
    return input_text

# Function to create a prompt for generating a threat model
def create_threat_model_prompt(app_type, authentication, internet_facing, sensitive_data, pam, remote_admin, development_model, operation_model, app_input):
    prompt = f"""
Act as a cyber security expert with more than 20 years experience of using the STRIDE threat modelling methodology to produce comprehensive threat models for a wide range of applications. Your task is to use the application description and additional provided to you to produce a list of specific threats for the application including the infrastructure and data assets.

For each of the STRIDE-LM categories (Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege, and Lateral Movement), list multiple (3 or 4) credible threats if applicable. Each threat scenario should provide a credible scenario in which the threat could occur in the context of the application, and you should provide relevant MITRE ATT&CK techniques if possible.

You must consider threats that could arise through the entire lifecycle ranging from the application architecture design, development, implementation, operation, and maintenance. In the case of web application, additionally include threats using the OWASP Top 10 as a reference.

It is very important that your responses are tailored to reflect the details you are given.

When providing the threat model, use a JSON formatted response with the keys "threat_model" and "improvement_suggestions". Under "threat_model", include an array of objects with the keys "Threat Type", "Scenario", and "Potential Impact". 

Under "improvement_suggestions", include an array of strings with suggestions on how the threat modeller can improve their application description in order to allow the tool to produce a more comprehensive threat model.

APPLICATION TYPE: {app_type}
AUTHENTICATION METHODS: {authentication}
INTERNET FACING: {internet_facing}
SENSITIVE DATA: {sensitive_data}
PRIVILEGED ACCESS MANAGEMENT: {pam}
REMOTE ADMINISTRATION: {remote_admin}
DEVELOPMENT MODEL: {development_model}
OPERATION MODEL: {operation_model}
APPLICATION DESCRIPTION: {app_input}

Example of expected JSON response format:
  
    {{
      "threat_model": [
        {{
          "Threat Type": "Spoofing",
          "Scenario": "Example Scenario 1",
          "Potential Impact": "Example Potential Impact 1",
          "MITRE ATT&CK Techniques": ["T1234 - Threat technique name 1", "T5678 - Threat technique name 2"]
        }},
        {{
          "Threat Type": "Spoofing",
          "Scenario": "Example Scenario 2",
          "Potential Impact": "Example Potential Impact 2",
          "MITRE ATT&CK Techniques": ["T1234 - Threat technique name 1", "T5678 - Threat technique name 2"]
        }},
        // ... more threats
      ],
      "improvement_suggestions": [
        "Example improvement suggestion 1.",
        "Example improvement suggestion 2.",
        // ... more suggestions
      ]
    }}
"""
    return prompt

# Function to get threat model from the GPT response.
def get_threat_model(api_key, model_name, prompt, max_tokens=4000, ragdb=None):
    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=model_name,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are a helpful assistant designed to output JSON."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=max_tokens,
    )

    # Convert the JSON string in the 'content' field to a Python dictionary
    response_content = json.loads(response.choices[0].message.content)

    return response_content

# Function to get threat model from the Azure OpenAI response.
def get_threat_model_azure(api_endpoint, api_key, api_version, deployment_name, prompt, ragdb=None):
    client = AzureOpenAI(
        azure_endpoint = api_endpoint,
        api_key = api_key,
        api_version = api_version,
    )

    response = client.chat.completions.create(
        model = deployment_name,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are a helpful assistant designed to output JSON."},
            {"role": "user", "content": prompt}
        ]
    )

    # Convert the JSON string in the 'content' field to a Python dictionary
    response_content = json.loads(response.choices[0].message.content)

    return response_content

# Function to get threat model from the Azure OpenAI response.
def get_threat_model_mistral(api_key, model_name, prompt, ragdb=None):
    client = MistralClient(api_key=api_key)

    response = client.chat(
        model = model_name,
        response_format={"type": "json_object"},
        messages=[
            ChatMessage(role="user", content=prompt)
        ]
    )

    # Convert the JSON string in the 'content' field to a Python dictionary
    response_content = json.loads(response.choices[0].message.content)

    return response_content

# Function to get threat model from Google Gemini.
def get_threat_model_gemini(api_key, model_name, prompt, ragdb=None):
    genai.configure(api_key=api_key)
    gemini_model = genai.GenerativeModel(model_name=model_name)

    response = gemini_model.generate_content(
        prompt
        # [model_behaviour, image_info[0], prompt],
        # model="gemini-pro-vision",
    )
    return response.text

# Function to get threat model from the GPT response.
def get_threat_model_local(model_name, prompt, ragdb=None):

    if ragdb is not None:
        llm = langchain_ollama(model_name=model_name)
        qa_chain = RetrievalQA(llm=llm, retriever=ragdb.as_retriever())

        response_content = qa_chain.run(prompt)

    else:
        response = ollama.chat(
            model=model_name,
            format='json',
            messages=[
                {"role": "system", "content": "You are a helpful assistant designed to output JSON."},
                {"role": "user", "content": prompt}
            ],
        )

        # Convert the JSON string in the 'content' field to a Python dictionary
        response_content = json.loads(response['message']['content'])

    return response_content

# Function to convert JSON to Markdown for display.    
def json_to_markdown(threat_model, improvement_suggestions):
    markdown_output = "## Threat Model\n\n"
    
    # Start the markdown table with headers
    markdown_output += "| Threat Type | Scenario | Potential Impact | MITRE ATT&CK |\n"
    markdown_output += "|-------------|----------|------------------|--------------|\n"
    
    # Fill the table rows with the threat model data
    for threat in threat_model:
        markdown_output += f"| {threat['Threat Type']} | {threat['Scenario']} | {threat['Potential Impact']} | {threat['MITRE ATT&CK Techniques']} |\n"
    
    markdown_output += "\n\n## Improvement Suggestions\n\n"
    for suggestion in improvement_suggestions:
        markdown_output += f"- {suggestion}\n"
    
    return markdown_output


# Function to create a prompt to generate an attack tree
def create_attack_tree_prompt(app_type, authentication, internet_facing, sensitive_data, pam, remote_admin, development_model, operation_model, app_input):
    prompt = f"""
APPLICATION TYPE: {app_type}
AUTHENTICATION METHODS: {authentication}
INTERNET FACING: {internet_facing}
SENSITIVE DATA: {sensitive_data}
PRIVILEGED ACCESS MANAGEMENT: {pam}
REMOTE ADMINISTRATION: {remote_admin}
DEVELOPMENT MODEL: {development_model}
OPERATION MODEL: {operation_model}
APPLICATION DESCRIPTION: {app_input}
"""
    return prompt


# Function to get attack tree from the GPT response.
def get_attack_tree(api_key, model_name, prompt):
    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": """
Act as a cyber security expert with more than 20 years experience of using the STRIDE threat modelling methodology to produce comprehensive threat models for a wide range of applications. Your task is to use the application description provided to you to produce an attack tree in Mermaid syntax. The attack tree should reflect the potential threats for the application based on the details given.

You MUST only respond with the Mermaid code block. See below for a simple example of the required format and syntax for your output.

```mermaid
graph TD
    A[Enter Chart Definition] --> B(Preview)
    B --> C{{decide}}
    C --> D["Keep"]
    C --> E["Edit Definition (Edit)"]
    E --> B
    D --> F["Save Image and Code"]
    F --> B
```

IMPORTANT: Round brackets are special characters in Mermaid syntax. If you want to use round brackets inside a node label you MUST wrap the label in double quotes. For example, ["Example Node Label (ENL)"].
"""},
            {"role": "user", "content": prompt}
        ]
    )

    # Access the 'content' attribute of the 'message' object directly
    attack_tree_code = response.choices[0].message.content
    
    # Remove Markdown code block delimiters using regular expression
    attack_tree_code = re.sub(r'^```mermaid\s*|\s*```$', '', attack_tree_code, flags=re.MULTILINE)

    return attack_tree_code

# Function to get attack tree from the Azure OpenAI response.
def get_attack_tree_azure(api_endpoint, api_key, api_version, deployment_name, prompt):
    client = AzureOpenAI(
        azure_endpoint = api_endpoint,
        api_key = api_key,
        api_version = api_version,
    )

    response = client.chat.completions.create(
        model = deployment_name,
        messages=[
            {"role": "system", "content": """
Act as a cyber security expert with more than 20 years experience of using the STRIDE threat modelling methodology to produce comprehensive threat models for a wide range of applications. Your task is to use the application description provided to you to produce an attack tree in Mermaid syntax. The attack tree should reflect the potential threats for the application based on the details given.

You MUST only respond with the Mermaid code block. See below for a simple example of the required format and syntax for your output.

```mermaid
graph TD
    A[Enter Chart Definition] --> B(Preview)
    B --> C{{decide}}
    C --> D["Keep"]
    C --> E["Edit Definition (Edit)"]
    E --> B
    D --> F["Save Image and Code"]
    F --> B
```

IMPORTANT: Round brackets are special characters in Mermaid syntax. If you want to use round brackets inside a node label you MUST wrap the label in double quotes. For example, ["Example Node Label (ENL)"].
"""},
            {"role": "user", "content": prompt}
        ]
    )

    # Access the 'content' attribute of the 'message' object directly
    attack_tree_code = response.choices[0].message.content
    
    # Remove Markdown code block delimiters using regular expression
    attack_tree_code = re.sub(r'^```mermaid\s*|\s*```$', '', attack_tree_code, flags=re.MULTILINE)

    return attack_tree_code


# Function to get attack tree from the Mistral model's response.
def get_attack_tree_mistral(api_key, model_name, prompt):
    client = MistralClient(api_key=api_key)

    response = client.chat(
        model=model_name,
        messages=[
            {"role": "system", "content": """
Act as a cyber security expert with more than 20 years experience of using the STRIDE threat modelling methodology to produce comprehensive threat models for a wide range of applications. Your task is to use the application description provided to you to produce an attack tree in Mermaid syntax. The attack tree should reflect the potential threats for the application based on the details given.

You MUST only respond with the Mermaid code block. See below for a simple example of the required format and syntax for your output.

```mermaid
graph TD
    A[Enter Chart Definition] --> B(Preview)
    B --> C{{decide}}
    C --> D["Keep"]
    C --> E["Edit Definition (Edit)"]
    E --> B
    D --> F["Save Image and Code"]
    F --> B
```

IMPORTANT: Round brackets are special characters in Mermaid syntax. If you want to use round brackets inside a node label you MUST wrap the label in double quotes. For example, ["Example Node Label (ENL)"].
"""},
            {"role": "user", "content": prompt}
        ]
    )

    # Access the 'content' attribute of the 'message' object directly
    attack_tree_code = response.choices[0].message.content
    
    # Remove Markdown code block delimiters using regular expression
    attack_tree_code = re.sub(r'^```mermaid\s*|\s*```$', '', attack_tree_code, flags=re.MULTILINE)

    return attack_tree_code

# Function to get attack tree from the Mistral model's response.
def get_attack_tree_gemini(api_key, model_name, prompt):
    genai.configure(api_key=api_key)
    gemini_model = genai.GenerativeModel(model_name=model_name)

    response = gemini_model.generate_content(
"""
Act as a cyber security expert with more than 20 years experience of using the STRIDE threat modelling methodology to produce comprehensive threat models for a wide range of applications. Your task is to use the application description provided to you to produce an attack tree in Mermaid syntax. The attack tree should reflect the potential threats for the application based on the details given.
You MUST only respond with the Mermaid code block. See below for a simple example of the required format and syntax for your output.

```mermaid
graph TD
    A[Enter Chart Definition] --> B(Preview)
    B --> C{{decide}}
    C --> D["Keep"]
    C --> E["Edit Definition (Edit)"]
    E --> B
    D --> F["Save Image and Code"]
    F --> B
```

IMPORTANT: Round brackets are special characters in Mermaid syntax. If you want to use round brackets inside a node label you MUST wrap the label in double quotes. For example, ["Example Node Label (ENL)"].

Below is the application description:
{prompt}
"""
    )

    # Access the 'content' attribute of the 'message' object directly
    attack_tree_code = response.text
    
    # Remove Markdown code block delimiters using regular expression
    attack_tree_code = re.sub(r'^```mermaid\s*|\s*```$', '', attack_tree_code, flags=re.MULTILINE)

    return attack_tree_code


# Function to get attack tree from the Local model's response.
def get_attack_tree_local(model_name, prompt):

    response = ollama.chat(
        model=model_name,
        messages=[
            {"role": "system", "content": """
Act as a cyber security expert with more than 20 years experience of using the STRIDE threat modelling methodology to produce comprehensive threat models for a wide range of applications. Your task is to use the application description provided to you to produce an attack tree in Mermaid syntax. The attack tree should reflect the potential threats for the application based on the details given.

You MUST only respond with the Mermaid code block. See below for a simple example of the required format and syntax for your output.

```mermaid
graph TD
    A[Enter Chart Definition] --> B(Preview)
    B --> C{{decide}}
    C --> D["Keep"]
    C --> E["Edit Definition (Edit)"]
    E --> B
    D --> F["Save Image and Code"]
    F --> B
```

IMPORTANT: Round brackets are special characters in Mermaid syntax. If you want to use round brackets inside a node label you MUST wrap the label in double quotes. For example, ["Example Node Label (ENL)"].
"""},
            {"role": "user", "content": prompt}
        ]
    )

    # Access the 'content' attribute of the 'message' object directly
    attack_tree_code = response['message']['content']
    
    # Remove Markdown code block delimiters using regular expression
    attack_tree_code = re.sub(r'^```mermaid\s*|\s*```$', '', attack_tree_code, flags=re.MULTILINE)

    return attack_tree_code

# Function to render Mermaid diagram
def mermaid(code: str, height: int = 500) -> None:
    components.html(
        f"""
        <pre class="mermaid" style="height: {height}px;">
            {code}
        </pre>

        <script type="module">
            import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
            mermaid.initialize({{ startOnLoad: true }});
        </script>
        """,
        height=height,
    )


# Function to create a prompt to generate mitigating controls
def create_mitigations_prompt(threats):
    prompt = f"""
Act as a cyber security expert with more than 20 years experience of using the STRIDE threat modelling methodology. Your task is to provide potential mitigations for the threats identified in the threat model. It is very important that your responses are tailored to reflect the details of the threats.

Your output should be in the form of a markdown table with the following columns:
    - Column A: Threat Type
    - Column B: Scenario
    - Column C: Suggested Mitigation(s)

Below is the list of identified threats:
{threats}

YOUR RESPONSE (do not wrap in a code block):
"""
    return prompt


# Function to get mitigations from the GPT response.
def get_mitigations(api_key, model_name, prompt):
    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model = model_name,
        messages=[
            {"role": "system", "content": "You are a helpful assistant that provides threat mitigation strategies in Markdown format."},
            {"role": "user", "content": prompt}
        ]
    )

    # Access the content directly as the response will be in text format
    mitigations = response.choices[0].message.content

    return mitigations


# Function to get mitigations from the Azure OpenAI response.
def get_mitigations_azure(api_endpoint, api_key, api_version, deployment_name, prompt):
    client = AzureOpenAI(
        azure_endpoint = api_endpoint,
        api_key = api_key,
        api_version = api_version,
    )

    response = client.chat.completions.create(
        model = deployment_name,
        messages=[
            {"role": "system", "content": "You are a helpful assistant that provides threat mitigation strategies in Markdown format."},
            {"role": "user", "content": prompt}
        ]
    )

    # Access the content directly as the response will be in text format
    mitigations = response.choices[0].message.content

    return mitigations


# Function to get mitigations from the Mistral model's response.
def get_mitigations_mistral(api_key, model_name, prompt):
    client = MistralClient(api_key=api_key)

    response = client.chat(
        model = model_name,
        messages=[
            {"role": "system", "content": "You are a helpful assistant that provides threat mitigation strategies in Markdown format."},
            {"role": "user", "content": prompt}
        ]
    )

    # Access the content directly as the response will be in text format
    mitigations = response.choices[0].message.content

    return mitigations

# Function to get mitigations from the Gemini.
def get_mitigations_gemini(api_key, model_name, prompt):
    genai.configure(api_key=api_key)
    gemini_model = genai.GenerativeModel(model_name=model_name)

    response = gemini_model.generate_content(
"""
Provide threat mitigation strategies in Markdown format.
{prompt}
"""
    )

    # Access the content directly as the response will be in text format
    mitigations = response.choices[0].message.content

    return mitigations

# Function to get mitigations from the local model's response.
def get_mitigations_local(model_name, prompt):

    response = ollama.chat(
        model = model_name,
        messages=[
            {"role": "system", "content": "You are a helpful assistant that provides threat mitigation strategies in Markdown format."},
            {"role": "user", "content": prompt}
        ]
    )

    # Access the content directly as the response will be in text format
    mitigations = response['message']['content']

    return mitigations