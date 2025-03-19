import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from urllib.parse import parse_qs, urlparse
import time
import json
import re
from datetime import datetime

class YouTubeScraper:
    def __init__(self, use_edge=True):
        """Initialize YouTube scraper with specified browser"""
        # Set up browser options
        if use_edge:
            options = EdgeOptions()
        else:
            options = ChromeOptions()
            
        # Configure browser options
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--start-maximized')
        options.add_argument('--disable-notifications')
        options.add_argument('--mute-audio')
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        # Initialize driver
        self.driver = webdriver.Edge(options=options) if use_edge else webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 15)
        
        # Hide automation
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        print(f"Started {'Edge' if use_edge else 'Chrome'} browser")
    
    def extract_video_id(self, url):
        """Extract YouTube video ID from URL"""
        if 'youtu.be' in url:
            return url.split('/')[-1].split('?')[0]
        elif 'youtube.com/watch' in url:
            parsed_url = urlparse(url)
            return parse_qs(parsed_url.query).get('v', [None])[0]
        elif 'youtube.com/shorts' in url or 'youtube.com/embed' in url:
            return url.split('/')[-1].split('?')[0]
        elif re.match(r'^[A-Za-z0-9_-]{11}$', url):  # Just the ID
            return url
        return None
    
    def get_video_info(self, video_url):
        """Get basic information about the video"""
        video_id = self.extract_video_id(video_url)
        if not video_id:
            print("Invalid YouTube URL")
            return None
            
        # Navigate to video
        url = f"https://www.youtube.com/watch?v={video_id}"
        self.driver.get(url)
        time.sleep(3)
        
        # Handle cookie consent if it appears
        cookie_buttons = self.driver.find_elements(By.XPATH, 
            "//button[contains(., 'Accept') or contains(., 'I agree')]")
        for button in cookie_buttons:
            if "accept" in button.text.lower() or "agree" in button.text.lower():
                button.click()
                time.sleep(1)
                break
        
        # Extract video info using simpler selectors
        video_info = {
            "video_id": video_id,
            "title": self._get_text("h1 yt-formatted-string", "Unknown Title"),
            "channel": self._get_text("ytd-channel-name a, #channel-name a", "Unknown Channel"),
            "views": self._get_text("span.view-count", "Unknown Views"),
            "upload_date": self._get_text("#info-strings yt-formatted-string", "Unknown Date"),
            "likes": self._get_text("ytd-toggle-button-renderer yt-formatted-string", "Unknown Likes"),
            "url": url
        }
        
        print(f"Video info extracted: '{video_info['title']}' by {video_info['channel']}")
        return video_info
    
    def _get_text(self, selector, default=""):
        """Helper to get text from an element or return default value"""
        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
        return elements[0].text if elements else default
    
    def scrape_comments(self, video_url, max_comments=None, sort_by="top"):
        """Scrape comments from a YouTube video with strict comment limit"""
        # Get video info
        video_info = self.get_video_info(video_url)
        if not video_info:
            return None
        
        # Scroll to comments section
        print("Scrolling to comments section...")
        self.driver.execute_script("window.scrollTo(0, document.querySelector('#comments').offsetTop);")
        time.sleep(2)
        
        # Sort comments if needed
        if sort_by.lower() == "newest":
            self._sort_comments_by_newest()
        
        # Collection variables
        comments = []
        last_comment_count = 0
        consecutive_unchanged = 0
        scroll_count = 0
        
        print(f"Starting to collect comments (max: {max_comments if max_comments else 'all'})...")
        
        # Main scraping loop
        while (not max_comments or len(comments) < max_comments) and scroll_count < 30 and consecutive_unchanged < 3:
            # Get current comments
            comment_elements = self.driver.find_elements(By.CSS_SELECTOR, "ytd-comment-thread-renderer")
            
            # Track if we've found new comments
            if len(comment_elements) > last_comment_count:
                print(f"Found {len(comment_elements)} comments so far")
                last_comment_count = len(comment_elements)
                consecutive_unchanged = 0
            else:
                consecutive_unchanged += 1
            
            # Process only new comments we haven't seen yet
            start_index = len(comments)
            end_index = min(len(comment_elements), 
                          len(comments) + 10,  
                          (max_comments or float('inf')))
            
            for i in range(start_index, end_index):
                comment_data = self._extract_comment(comment_elements[i])
                if comment_data:
                    comments.append(comment_data)
                    # Stop if we've reached the limit
                    if max_comments and len(comments) >= max_comments:
                        break
            
            # Print progress periodically
            if len(comments) % 10 == 0 and len(comments) > 0:
                print(f"Extracted {len(comments)} comments")
            
            # Break if we've hit our limit
            if max_comments and len(comments) >= max_comments:
                print(f"Reached maximum comment limit ({max_comments})")
                break
                
            # Scroll to load more comments
            self.driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(2)
            scroll_count += 1
        
        # Create final result object
        result = {
            "video_info": video_info,
            "comments": comments[:max_comments] if max_comments else comments,  # Ensure we don't exceed max
            "metadata": {
                "total_comments_collected": min(len(comments), max_comments if max_comments else len(comments)),
                "sort_order": sort_by,
                "scrape_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }
        
        print(f"Successfully scraped {len(result['comments'])} comments")
        return result
    
    def _sort_comments_by_newest(self):
        """Sort YouTube comments by newest first"""
        # Try to click sort button and select "Newest first"
        sort_button = self.driver.find_elements(By.CSS_SELECTOR, 
            "ytd-sort-filter-submenus-renderer yt-sort-filter-sub-menu-renderer")
        if not sort_button:
            return
            
        sort_button[0].click()
        time.sleep(1)
        
        newest_options = self.driver.find_elements(By.XPATH, "//paper-item[contains(., 'Newest first')]")
        if newest_options:
            newest_options[0].click()
            time.sleep(2)
            print("Changed sort order to: Newest first")
    
    def _extract_comment(self, comment_element):
        """Extract data from a comment element"""
        author = self._get_element_text(comment_element, "#author-text")
        text = self._get_element_text(comment_element, "#content-text")
        likes = self._get_element_text(comment_element, "#vote-count-middle") or "0"
        timestamp = self._get_element_text(comment_element, ".published-time-text") or "Unknown"
        
        # Only return if we have meaningful content
        if author and text:
            return {
                "author": author,
                "text": text,
                "likes": likes,
                "timestamp": timestamp
            }
        return None
    
    def _get_element_text(self, parent, selector):
        """Get text from a child element using CSS selector"""
        elements = parent.find_elements(By.CSS_SELECTOR, selector)
        return elements[0].text.strip() if elements else ""
    
    def save_to_json(self, data, filename):
        """Save data to JSON file"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Data saved to: {filename}")
        
    def save_to_csv(self, data, filename):
        """Save comments to CSV file"""
        if data and "comments" in data and data["comments"]:
            df = pd.DataFrame(data["comments"])
            df.to_csv(filename, index=False, encoding='utf-8-sig')
            print(f"Comments saved to: {filename}")
            
    def close(self):
        """Close the browser"""
        if self.driver:
            self.driver.quit()
            print("Browser closed")

def main():
    # Get user input
    print("\n=== YouTube Comment Scraper ===\n")
    
    video_url = input("Enter YouTube video URL: ")
    max_comments = input("Enter maximum comments to scrape (press Enter for all): ")
    sort_option = input("Sort comments by (top/newest, default: top): ").lower() or "top"
    output_format = input("Output format (csv/json/both, default: json): ").lower() or "json"
    browser_choice = input("Browser (edge/chrome, default: edge): ").lower() or "edge"
    
    # Process inputs
    max_comments = int(max_comments) if max_comments and max_comments.isdigit() else None
    use_edge = browser_choice != "chrome"
    
    # Generate filenames
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    
    # Run scraper
    scraper = YouTubeScraper(use_edge=use_edge)
    
    try:
        # Get video ID for filename
        video_id = scraper.extract_video_id(video_url) or "video"
        base_filename = f"yt_comments_{video_id}_{timestamp}"
        
        # Scrape comments
        data = scraper.scrape_comments(video_url, max_comments, sort_option)
        
        if data:
            # Save output files
            if output_format in ["json", "both"]:
                scraper.save_to_json(data, f"{base_filename}.json")
            
            if output_format in ["csv", "both"]:
                scraper.save_to_csv(data, f"{base_filename}.csv")
            
            print(f"\nScraping complete! Collected {len(data['comments'])} comments")
        else:
            print("Failed to scrape comments")
            
    finally:
        scraper.close()

if __name__ == "__main__":
    main()