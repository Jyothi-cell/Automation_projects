'''import requests
import xml.etree.ElementTree as ET
import sys



def fetch_data_by_document_uuid(guid_uuid):
    """Fetch data from the URL using the DocumentUuid."""
    url = f"http://dataprocessingtools.int.thomsonreuters.com/pgs_Tools_Novus/GetNovusDocsByGuid.aspx?uid={guid_uuid}&env=P"
    print(f"Constructed URL: {url}")
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            print("Successfully fetched data.")
            return response.content
        else:
            print(f"Failed to fetch data. Status Code: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {str(e)}")
        return None

def main(guid_uuid):
    # Fetch data using the DocumentUuid
    fetched_data = fetch_data_by_document_uuid(guid_uuid)
    
    if fetched_data:
        # Write fetched data to a file named after the DocumentUuid
        filename = f"{guid_uuid}.xml"
        with open(filename, "wb") as file:
            file.write(fetched_data)
        print(f"Data written to {filename}")

if __name__ == "__main__":
    guid_uuid = sys.argv[1]  # Replace with your actual DocumentUuid
    main(guid_uuid)'''
    
'''import requests
import xml.etree.ElementTree as ET
import sys

def fetch_data_by_document_uuid(guid_uuid):
    """Fetch data from the URL using the DocumentUuid."""
    url = f"http://dataprocessingtools.int.thomsonreuters.com/pgs_Tools_Novus/GetNovusDocsByGuid.aspx?uid={guid_uuid}&env=P"
    print(f"Constructed URL: {url}")
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            print("Successfully fetched data.")
            return response.content
        else:
            print(f"Failed to fetch data. Status Code: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {str(e)}")
        return None

def extract_attorney_info(xml_content):
    """Extract specific attorney information from XML content."""
    root = ET.fromstring(xml_content)

    # Find the relevant tags
    attorney_name = root.findtext('.//attorney.name/cite.query')
    attorney_status = root.findtext('.//attorney.status')
    city = root.findtext('.//city')
    state = root.findtext('.//state')

    # Check if all elements were found and construct the formatted line
    if attorney_name and attorney_status and city and state:
        attorney_line = f"<content.attorney.block><content.attorney><attorney.line first-line=\"1\">{attorney_name}, {attorney_status}, {city}, {state}.</attorney.line></content.attorney></content.attorney.block>"
        print(attorney_line)
        return attorney_line
    else:
        print("Required information is missing in the XML.")
        return None

def main(guid_uuid):
    # Fetch data using the DocumentUuid
    fetched_data = fetch_data_by_document_uuid(guid_uuid)
    
    if fetched_data:
        # Save the XML data to a file
        filename = f"{guid_uuid}.xml"
        with open(filename, "wb") as file:
            file.write(fetched_data)
        print(f"Data written to {filename}")

        # Extract and print the attorney information
        extract_attorney_info(fetched_data)

if __name__ == "__main__":
    guid_uuid = sys.argv[1]  # Replace with your actual DocumentUuid
    main(guid_uuid)'''

import requests
import xml.etree.ElementTree as ET
import streamlit as st

def fetch_data_by_document_uuid(guid_uuid):
    """Fetch data from the URL using the DocumentUuid."""
    url = f"http://dataprocessingtools.int.thomsonreuters.com/pgs_Tools_Novus/GetNovusDocsByGuid.aspx?uid={guid_uuid}&env=P"
    st.write(f"Constructed URL: {url}")
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            st.success("Successfully fetched data.")
            return response.content
        else:
            st.error(f"Failed to fetch data. Status Code: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"An error occurred: {str(e)}")
        return None

def extract_attorney_info(xml_content):
    """Extract specific attorney information from XML content."""
    root = ET.fromstring(xml_content)

    # Find all relevant tags
    attorney_names = root.findall('.//attorney.name/cite.query')
    attorney_statuses = root.findall('.//attorney.status')
    cities = root.findall('.//city')
    states = root.findall('.//state')

    # Check that we have the same number of each tag type
    if len(attorney_names) == len(attorney_statuses) == len(cities) == len(states):
        for name, status, city, state in zip(attorney_names, attorney_statuses, cities, states):
            attorney_line = f"<content.attorney.block><content.attorney><attorney.line first-line=\"1\">{name.text}, {status.text}, {city.text}, {state.text}.</attorney.line></content.attorney></content.attorney.block>"
            st.write(attorney_line)
    else:
        st.warning("Mismatch in the number of elements found in the XML.")

def main():
    st.title("Attorney Information Extractor")

    guid_uuid = st.text_input("Enter Document UUID:")
    
    if st.button("Fetch and Extract Information"):
        if guid_uuid:
            # Fetch data using the DocumentUuid
            fetched_data = fetch_data_by_document_uuid(guid_uuid)
            
            if fetched_data:
                # Extract and display the attorney information
                extract_attorney_info(fetched_data)
        else:
            st.warning("Please enter a valid Document UUID.")

if __name__ == "__main__":
    main()